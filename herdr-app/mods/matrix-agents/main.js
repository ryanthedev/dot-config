// Agents in grouped or priority views; parents take their most urgent sub-agent's place.
// A viewed done agent stays in Done until left.

import { View, div, image, svg } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { agents, terminals, panes, focused, spaces, run, theme, shared, setShared, setAgentOrder, openOverlay, closeOverlay, props, window, layout, nextCommand } from "herdr";

function find(node, id) {
  if (node?.id === id) return node;
  for (const child of node?.children ?? []) {
    const found = find(child, id);
    if (found) return found;
  }
  return null;
}

// The sidebar's rail goes by its width, not a flag: dragging its edge narrows it too.
const narrow = () => (find(layout(), "sidebar")?.size?.px ?? Infinity) < 160;

// To the rail (on macOS wide enough for the traffic lights), or back to the width it had.
function toggleSidebar() {
  const width = find(layout(), "sidebar")?.size?.px;
  if (!narrow()) setShared("sidebar.width", width);
  // Mods edited before the rail went by width still read the flag.
  setShared("sidebar.collapsed", !narrow());
  run("layout.resize", { id: "sidebar", px: narrow() ? (shared("sidebar.width") ?? 268) : window()?.platform === "macos" ? 76 : 44 });
}

const clean = (s) => (s ?? "").replace(/^[^\p{L}\p{N}]+/u, "").trim();

function leadPanes(all) {
  const leads = new Map();
  for (const p of all) {
    if (!p.terminal) continue;
    const current = leads.get(p.tab);
    // First agent, else first focused terminal, else first terminal in the tab.
    if (!current || (!current.program?.agent && (p.program?.agent || (!current.focused && p.focused)))) leads.set(p.tab, p);
  }
  return leads;
}

function title(tab, l) {
  const prog = l?.program?.name;
  const live = clean(l?.title);
  const telling = live && live !== prog && !/^[~/]|^[A-Za-z]:\\/.test(live) && !live.includes("@") && live.toLowerCase() !== l?.program?.key;
  return (tab.name === prog || !tab.named) && telling ? live : tab.name;
}
const RANK = { blocked: 4, done: 3, working: 2, idle: 1 };
// A sub-agent without a pane isn't in agents(): its raw word, error counting as
// blocked. It's never done: it reports to its parent, and the parent's done is the news.
const kidStatus = (k, listed) => {
  const s = listed.get(k.address) ?? k.status;
  return s === "error" ? "blocked" : s === "done" ? "idle" : s;
};
const SORTS = [
  { id: "spaces", label: "Spaces (compact)", icon: "folder" },
  { id: "priority", label: "Priority", icon: "clock" },
  { id: "grouped", label: "Grouped by space", icon: "layers" },
];
const sortOf = () => SORTS.find((s) => s.id === shared("agents.sort")) ?? SORTS[0];
const SECTION = { 4: "Anomaly: needs you", 3: "Mission complete", 2: "In pursuit", 1: "Standing by" };

const SECTION_STATUS = { 4: "blocked", 3: "done", 2: "working" };
const STATUS_OF = { 4: "blocked", 3: "done", 2: "working", 1: "idle" };
// Space colors as matrix-spaces draws them (shared "space.colors"), so a space's
// row here matches its bar in FLEET.
const MARK = { ansi6: "#22a99a", ansi3: "#e3814f", ansi4: "#5b8def", ansi5: "#8b7cf6", ansi2: "#3fae6a", ansi1: "#d9649a" };
function spaceFill(t, id) {
  const c = (shared("space.colors") ?? {})[id] ?? "ansi6";
  return c.startsWith("#") ? c : (MARK[c] ?? t[c] ?? t.dim);
}

function duration(ms) {
  const m = Math.floor(ms / 60000);
  if (m < 1) return "<1m";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

// The agent's icon from the app's program table: a one-color glyph or a picture.
function icon(p, size, color) {
  if (!p?.icon) return null;
  return p.tint ? svg(p.icon).size(size).flex_none().text_color(color) : image(p.icon).w(size).h(size).flex_none();
}

export default class Agents extends View {
  init(_props, cx) {
    if (props()?.sortMenu) return;
    if (props()?.spaceList) {
      // The popup of one space's agents: arrows or j/k move, Enter goes, 1-9 jump.
      this.at = 0;
      this.changed = JSON.parse(localStorage.getItem("changed") ?? "{}");
      this.handle = cx.focus_handle();
      this.handle.focus();
      cx.timer.after(80, () => this.handle.focus());
      return;
    }
    this.folded = new Set();
    localStorage.removeItem("opened");
    // Each agent's last state and when it changed (ms), kept across restarts.
    this.changed = JSON.parse(localStorage.getItem("changed") ?? "{}");
    this.pendingPins = JSON.parse(localStorage.getItem("pins") ?? "[]");
    if (!this.pendingPins.length) localStorage.removeItem("pins");
    this.migratingPins = new Set();
    cx.timer.every(30000, (cx) => cx.notify());
    // ctrl+1..9 (keys.json, layout:matrix) send "agent1".."agent9": show that
    // row of the list, in the order it's drawn (pins first, then the sort).
    this.order = [];
    cx.spawn(async (cx) => {
      for (;;) {
        const n = /^agent([1-9])$/.exec(await nextCommand())?.[1];
        const address = n && this.order[n - 1];
        if (address) run("agent.focus", { terminal: address });
      }
    });
  }

  // Stamps agents whose state changed. Done and idle count as one: looking at a
  // finished agent turns done into idle, and looking isn't the agent doing anything.
  track(list, now) {
    let dirty = false;
    for (const a of list) {
      const s = a.status === "done" ? "idle" : a.status;
      if (this.changed[a.address]?.s === s) continue;
      this.changed[a.address] = { s, at: now };
      dirty = true;
    }
    if (!dirty) return;
    // Gone and old: the list alone is empty right after a start.
    const listed = new Set(list.map((a) => a.address));
    for (const [k, c] of Object.entries(this.changed)) if (!listed.has(k) && now - c.at > 30 * 86400000) delete this.changed[k];
    localStorage.setItem("changed", JSON.stringify(this.changed));
  }

  // Keep offline pins until their terminal returns, and keep each pending until
  // core echoes the label so a failed write doesn't erase the old pin.
  migratePins(all) {
    const listed = new Map(all.filter((t) => t.state === "live").map((t) => [t.address, t]));
    const pending = this.pendingPins.filter((address) => {
      const terminal = listed.get(address);
      if (!terminal) return true;
      if (terminal.labels?.["herdr.pinned"]) return false;
      if (!this.migratingPins.has(address)) {
        this.migratingPins.add(address);
        run("terminal.pin", { terminal: address, pinned: true });
      }
      return true;
    });
    if (pending.length === this.pendingPins.length) return;
    this.pendingPins = pending;
    if (pending.length) localStorage.setItem("pins", JSON.stringify(pending));
    else localStorage.removeItem("pins");
  }

  since(a) {
    return this.changed[a.address]?.at ?? 0;
  }

  // Looking at a done agent makes it idle; it stays with Done until you leave
  // it rather than drop away under you. Any other change moves it at once.
  hold(list) {
    const cur = list.find((a) => a.focused);
    const same = cur && cur.address === this.held?.address;
    // Arriving, or any change but done turning idle, sets what it was.
    if (!same || cur.status !== "idle") this.held = cur ? { address: cur.address, rank: RANK[cur.status] ?? 0 } : null;
  }

  rank(a) {
    const sawDone = a.address === this.held?.address && this.held.rank === RANK.done && a.status === "idle";
    return sawDone ? RANK.done : RANK[a.status] ?? 0;
  }

  sortMenu(t) {
    const on = sortOf().id;
    return v_flex()
      .w_full()
      .p(5)
      .bg(t.popover)
      .text_size(12.8)
      .child(div().px(8).pt(4).pb(6).text_size(11).text_color(t.dim).child("Sort agents"))
      .children(SORTS.map((s) => h_flex()
        .id(`sort-${s.id}`)
        .h(31)
        .px(8)
        .gap(9)
        .rounded(7)
        .items_center()
        .text_color(t.foreground)
        .hover((el) => el.bg(t.hover))
        .on_click(() => {
          setShared("agents.sort", s.id);
          closeOverlay(props().overlay);
        })
        .child(svg(`mods/workspace-chrome/${s.icon}.svg`).size(14).flex_none().text_color(t.muted))
        .child(div().flex_1().child(s.label))
        .when(s.id === on, (el) => el.child(svg("mods/workspace-chrome/check.svg").size(14).flex_none().text_color(t.foreground)))));
  }

  // One space's agents, most urgent first, in a popup that takes the keyboard.
  spaceList(t, cx) {
    const id = props().spaceList;
    const sp = spaces().find((s) => s.id === id);
    const list = agents()
      .filter((a) => a.space === id)
      .sort((x, y) => (RANK[y.status] ?? 0) - (RANK[x.status] ?? 0) || this.since(y) - this.since(x));
    const now = Date.now();
    const fill = spaceFill(t, id);
    this.at = Math.max(0, Math.min(this.at, list.length - 1));
    const close = () => closeOverlay(props().overlay);
    const go = (a) => {
      if (!a) return;
      close();
      run("pane.focus", { pane: a.pane });
    };
    const taskOf = (a) => {
      const prog = a.program?.name ?? "";
      const own = clean(a.title);
      const telling = own && own.toLowerCase() !== prog.toLowerCase() && own.toLowerCase() !== a.program?.key && !/^[~/]/.test(own);
      return telling ? own : (a.tab_name && !/^\d+$/.test(a.tab_name) ? a.tab_name : prog || a.address);
    };
    return v_flex()
      .id("space-list")
      .track_focus(this.handle)
      .size_full()
      .p(6)
      .bg(t.popover)
      .text_size(13)
      .on_key_down((e, cx) => {
        const k = e.key;
        if (k === "escape") return close();
        if (k === "down" || k === "j") this.at = (this.at + 1) % Math.max(1, list.length);
        else if (k === "up" || k === "k") this.at = (this.at + list.length - 1) % Math.max(1, list.length);
        else if (k === "enter") return go(list[this.at]);
        else if (/^[1-9]$/.test(k) && list[+k - 1]) return go(list[+k - 1]);
        else return;
        cx.stop_propagation();
        cx.notify();
      })
      .child(h_flex().px(8).pt(4).pb(8).gap(8).items_center()
        .child(div().w(3).h(14).flex_none().rounded(2).bg(fill))
        .child(div().flex_1().truncate().text_size(12).font_medium().text_color(t.foreground).child(sp?.name ?? "Space"))
        .child(div().flex_none().text_size(10.5).text_color(t.dim).child("\u2191\u2193 \u21b5  esc")))
      .when(list.length === 0, (el) => el.child(div().px(8).py(6).text_size(12).text_color(t.dim).child("No agents in this space.")))
      .children(list.map((a, i) => {
        const on = i === this.at;
        const when = this.since(a);
        return h_flex()
          .id(`sl-${a.address}`)
          .h(40)
          .px(8)
          .gap(8)
          .flex_none()
          .rounded(6)
          .items_center()
          .when(on, (el) => el.bg(t.selected))
          .when(!on, (el) => el.hover((s) => s.bg(t.hover)))
          .cursor_pointer()
          .on_hover((over, cx) => {
            if (over && this.at !== i) {
              this.at = i;
              cx.notify();
            }
          })
          .on_click(() => go(a))
          .child(div().w(10).flex_none().text_right().text_size(11).text_color(t.dim).child(i < 9 ? String(i + 1) : ""))
          .child(v_flex().flex_1().min_w(0)
            .child(div().truncate().font_medium().text_color(a.status === "idle" ? t.muted : t.foreground).child(taskOf(a)))
            .child(div().truncate().text_size(11).text_color(t.dim).child([a.tab_name && !/^\d+$/.test(a.tab_name) ? a.tab_name : `tab ${a.tab_name ?? ""}`.trim(), a.app === "claude-code" ? null : a.program?.name].filter(Boolean).join(" \u00b7 "))))
          .when(Boolean(when), (el) => el.child(div().flex_none().text_size(11).text_color(t.dim).child(duration(now - when))))
          .child(h_flex().w(14).flex_none().justify_center().child(this.status(t, a, true)));
      }));
  }

  peek(addr) {
    run("terminal.peek", { terminal: addr });
  }

  // Live sub-agents of `addr`, depth first, each with the tree lines in front of it.
  tree(all, addr, lead = []) {
    const kids = all.filter((k) => k.parent === addr && k.state === "live");
    return kids.flatMap((k, i) => {
      const last = i === kids.length - 1;
      return [
        { t: k, lines: [...lead, last ? "└" : "├"] },
        ...this.tree(all, k.address, [...lead, last ? "" : "│"]),
      ];
    });
  }

  subRow(t, s, shown, compact) {
    const k = s.t;
    const st = kidStatus(k, this.listed);
    const on = k.address === shown;
    return h_flex()
      .id(`sub-${k.address}`)
      .pl(26)
      .pr(8)
      .rounded(8)
      .h(26)
      .flex_none()
      .gap(0)
      .items_center()
      .text_size(12.5)
      .when(on, (el) => el.bg(t.raised))
      .hover((s) => s.bg(t.hover))
      .on_click(() => this.peek(k.address))
      .children(s.lines.map(l => div().self_start().mt(-4).w(9).h(17).mr(4).flex_none()
        .when(Boolean(l), el => el.border_l(1.5).border_color(t.input))
        .when(l === "└" || l === "├", el => el.border_b(1.5).rounded_bl(6))))
      .child(div().flex_1().truncate().text_color(on ? t.foreground : t.muted).child(k.name || k.template || k.program?.name || k.address))
      .child(this.status(t, { status: st }, compact));
  }

  // compact: a ! for blocked where a header already says "Needs you".
  status(t, a, compact = false) {
    const color = t[a.status] ?? t.dim;
    if (a.status === "working") return svg("mods/workspace-chrome/spinner.svg").size(12).mx(1).flex_none().text_color(t.working).spin(900);
    if (a.status === "blocked" && compact) return div().size(14).flex_none().rounded(4).bg(t.blocked + "26").text_size(10.5).font_bold().text_color(t.blocked).flex().items_center().justify_center().child("!");
    if (a.status === "blocked") return div().flex_none().px(6).h(18).rounded(5).bg(t.blocked + "26").text_size(10.5).font_semibold().text_color(t.blocked).flex().items_center().child("Needs you");
    // Idle: a ring; done: a dot.
    if (a.status === "idle") return div().size(7).mx(3).flex_none().rounded(4).border(1.5).border_color(t.idle ?? t.dim);
    return div().size(7).mx(3).flex_none().rounded(4).bg(a.status === "done" ? color : t.dim + "00");
  }

  render(cx) {
    const t = theme();
    if (props()?.sortMenu) return this.sortMenu(t);
    if (props()?.spaceList) return this.spaceList(t, cx);
    const collapsed = narrow();
    const sort = sortOf();
    let list = agents();
    this.listed = new Map(list.map((a) => [a.address, a.status]));
    const all = terminals();
    this.migratePins(all);
    const shown = focused()?.agent;
    const now = Date.now();
    this.track(list, now);
    this.hold(list);
    const byPriority = sort.id === "priority";
    const bySpace = sort.id === "spaces";
    const urgency = new Map(list.map((a) => [a.address, Math.max(this.rank(a), ...this.tree(all, a.address).map((s) => RANK[kidStatus(s.t, this.listed)] ?? 0))]));
    const rankOf = (a) => urgency.get(a.address);
    if (byPriority) list = [...list].sort((x, y) => rankOf(y) - rankOf(x) || this.since(y) - this.since(x) || y.seq - x.seq);
    const pinned = list.filter((a) => a.pinned);
    const rest = list.filter((a) => !a.pinned);
    list = [...pinned, ...rest];
    setAgentOrder(list.map((a) => a.address));
    this.order = list.map((a) => a.address);

    // Spaces view: every unpinned agent folds into one row per space. The row
    // goes to its most urgent agent (needs you, then done, then working),
    // most recently changed first; ctrl+N counts space rows, not agents.
    const spaceGroups = [];
    if (bySpace) {
      const bySp = new Map();
      for (const a of rest) {
        let g = bySp.get(a.space);
        if (!g) {
          g = { id: `sp-${a.space}`, space: a.space, label: a.space_name || "", members: [] };
          bySp.set(a.space, g);
          spaceGroups.push(g);
        }
        g.members.push(a);
      }
      for (const g of spaceGroups) {
        g.pick = [...g.members].sort((x, y) => (rankOf(y) || 1) - (rankOf(x) || 1) || this.since(y) - this.since(x))[0];
        g.rank = rankOf(g.pick) || RANK.idle;
      }
      this.order = [...pinned.map((a) => a.address), ...spaceGroups.map((g) => g.pick.address)];
    }

    const withKids = (a, i) => {
      const subs = collapsed ? [] : this.tree(all, a.address);
      const r = row(a, i, subs);
      if (this.folded.has(a.address)) return [r];
      return [r, ...subs.map((s) => this.subRow(t, s, shown, byPriority))];
    };

    // The fold chevron; folded, the count too, colored by the most urgent one.
    const fold = (a, subs) => {
      const sts = subs.map((s) => kidStatus(s.t, this.listed));
      const top = sts.reduce((m, s) => ((RANK[s] ?? 0) > (RANK[m] ?? 0) ? s : m), null);
      const open = !this.folded.has(a.address);
      return div()
        .id(`fold-${a.address}`)
        .h(18)
        .px(3)
        .gap(3)
        .flex()
        .items_center()
        .rounded(4)
        .text_size(11)
        .text_color(open ? t.dim : (t[top] ?? t.dim))
        .cursor_pointer()
        .hover((s) => s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => {
          cx.stop_propagation();
          open ? this.folded.add(a.address) : this.folded.delete(a.address);
          cx.notify();
        })
        .child(svg(`mods/workspace-chrome/chevron-${open ? "down" : "right"}.svg`).size(11).flex_none())
        .when(!open, (el) => el.child(String(subs.length)));
    };

    // A row reads "space \u00b7 detail": the detail is a tab someone named or the
    // agent's own title, never an automatic tab number unless two rows would
    // otherwise read the same.
    // Read the pane snapshot once: every host read copies the whole list into JS.
    const allPanes = panes();
    const paneOf = new Map(allPanes.map((p) => [p.pane, p]));
    const leads = leadPanes(allPanes);
    const tabLabels = new Map(spaces().flatMap(s => s.tabs).map(tab => [tab.id, title(tab, leads.get(tab.id))]));
    const labels = new Map(list.map(a => [a.address, tabLabels.get(a.tab) ?? (a.title || a.program?.name || "")]));
    const label = (a) => labels.get(a.address);
    const detail = new Map(list.map(a => [a.address, /^\d+$/.test(label(a)) ? null : label(a)]));
    const seen = {};
    for (const a of list) { const k = `${a.space_name}\u0000${detail.get(a.address) ?? ""}`; seen[k] = (seen[k] ?? 0) + 1; }
    for (const a of list) {
      if (detail.get(a.address) == null && seen[`${a.space_name}\u0000`] > 1) detail.set(a.address, label(a));
    }

    const row = (a, i, subs = []) => {
      const more = detail.get(a.address);
      // An agent on another machine (`vps/t7`) says which.
      const machine = a.address.includes("/") ? a.address.split("/")[0] : null;
      if (collapsed) {
        return h_flex()
          .id(`ag-${a.address}`)
          .h(26)
          .px(8)
          .flex_none()
          .items_center()
          .gap(4)
          .hover((s) => s.bg(t.hover))
          .on_click(() => run("pane.focus", { pane: a.pane }))
          .child(div().flex_1().min_w(0).whitespace_nowrap().text_right().text_color(t.muted).child(String(i + 1)))
          .child(h_flex().w(14).flex_none().items_center().justify_center().child(this.status(t, a, true)));
      }
      const when = this.since(a);
      const idle = a.status === "idle" && !a.focused;
      const isPinned = a.pinned;
      const pin = div()
        .id(`pin-${a.address}`)
        .flex_none()
        .p(2)
        .rounded(4)
        .text_color(t.dim)
        .cursor_pointer()
        .hover((s) => s.bg(t.hover).text_color(t.foreground))
        .tooltip(isPinned ? "Unpin" : "Pin to the top")
        .on_click((_e, cx) => {
          cx.stop_propagation();
          run("terminal.pin", { terminal: a.address, pinned: !isPinned });
          // The row moves away from under the pointer, and no hover-out comes.
          this.hovered = null;
          cx.notify();
        })
        .child(svg(`mods/workspace-chrome/${isPinned ? "pin-off" : "pin"}.svg`).size(13));
      // Line 1: what the agent says it's doing (its terminal title), else its tab.
      // Line 2: where it is: space, branch, a named tab, the program when it isn't Claude Code, the machine.
      const pane = paneOf.get(a.pane);
      const prog = a.program?.name ?? "";
      const own = clean(a.title);
      const telling = own && own.toLowerCase() !== prog.toLowerCase() && own.toLowerCase() !== a.program?.key && !/^[~/]/.test(own);
      const task = telling ? own : (more ?? label(a) ?? prog);
      const branch = pane?.branch && !["main", "master"].includes(pane.branch) ? pane.branch : null;
      const seenPart = new Set([task.toLowerCase()]);
      const parts = [a.space_name, branch, a.tab_name && !/^\d+$/.test(a.tab_name) ? a.tab_name : null, a.app === "claude-code" ? null : prog, machine]
        .filter((x) => x && !seenPart.has(x.toLowerCase()) && seenPart.add(x.toLowerCase()));
      const n = bySpace && !a.pinned ? 0 : this.order.indexOf(a.address) + 1;
      return h_flex()
        .id(`ag-${a.address}`)
        .pl(6)
        .pr(8)
        .py(6)
        .flex_none()
        .rounded(6)
        .items_start()
        .gap(8)
        .when(a.focused, (el) => el.bg(t.selected))
        .cursor_pointer()
        .hover((s) => s.bg(t.hover))
        .on_hover((on, cx) => {
          if (on) this.hovered = a.address;
          else if (this.hovered === a.address) this.hovered = null;
          cx.notify();
        })
        .on_click(() => run("pane.focus", { pane: a.pane }))
        // ctrl+N reaches rows 1..9; the number is the hint.
        .child(div().id(`agent-fold-${a.address}`).w(12).flex_none().text_right().text_size(11).text_color(t.dim)
          .when(subs.length > 0, el => el.on_click((_e, cx) => {
            cx.stop_propagation();
            this.folded.has(a.address) ? this.folded.delete(a.address) : this.folded.add(a.address);
            cx.notify();
          }))
          .child(n >= 1 && n <= 9 ? String(n) : ""))
        .child(v_flex().flex_1().min_w(0).gap(1)
          .child(h_flex().gap(6).items_center()
            .child(div().flex_1().min_w(0).truncate().text_color(idle ? t.muted : t.foreground).font_medium().child(task))
            .when(subs.length > 0, el => el.child(fold(a, subs)))
            .when(this.hovered === a.address, el => el.child(pin))
            .when(this.hovered !== a.address && Boolean(when), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(duration(now - when))))
            .child(h_flex().w(14).flex_none().justify_center().child(this.status(t, a, byPriority && !isPinned))))
          .when(parts.length > 0, el => el.child(div().truncate().text_size(11.5).text_color(t.dim).child(parts.join(" \u00b7 ")))));
    };

    // Groups in list order: spaces (grouped) or priority sections. Agents of a
    // space are next to each other in agents(), so neighbours make a group.
    const groups = pinned.length ? [{ id: "pinned", label: "Pinned", status: null, members: pinned }] : [];
    for (const a of rest) {
      const r = rankOf(a) || RANK.idle;
      const id = byPriority ? `sec-${r}` : `sp-${a.space}`;
      if (groups.at(-1)?.id === id) groups.at(-1).members.push(a);
      else groups.push({ id, label: byPriority ? SECTION[r] : a.space_name || "", status: byPriority ? SECTION_STATUS[r] : null, members: [a] });
    }

    // A group's header; it folds the group. Folded, it says how many and the most urgent state.
    const header = (g) => {
      const open = !this.folded.has(g.id);
      const top = g.members.reduce((m, a) => ((RANK[a.status] ?? 0) > (RANK[m] ?? 0) ? a.status : m), null);
      return h_flex()
        .id(g.id)
        .px(8)
        .pt(8)
        .h(30)
        .flex_none()
        .gap(6)
        .items_center()
        .text_size(11)
        .font_medium()
        .cursor_pointer()
        .hover((s) => s.text_color(t.foreground))
        .on_click((_e, cx) => {
          open ? this.folded.add(g.id) : this.folded.delete(g.id);
          cx.notify();
        })
        .child(div().truncate().text_color(t[g.status] ?? t.dim).child(g.label))
        .when(byPriority || !open, (el) => el.child(div().text_color(t.dim).child(String(g.members.length))))
        .child(div().flex_1())
        .when(!open, (el) => el
          .when(!byPriority && top && top !== "idle", (el) => el.child(this.status(t, { status: top }, true)))
          .child(svg("mods/workspace-chrome/chevron-right.svg").size(11).flex_none().text_color(t.dim)));
    };
    // One space: its color bar, name, and a count of its agents by state.
    const spaceRow = (g, n) => {
      const fill = spaceFill(t, g.space);
      const here = g.members.some((a) => a.focused);
      const counts = [[4, "needs you"], [2, "working"], [3, "done"], [1, "idle"]]
        .map(([r, word]) => ({ r, word, n: g.members.filter((a) => (rankOf(a) || RANK.idle) === r).length }))
        .filter((c) => c.n);
      return h_flex()
        .id(g.id)
        .pl(6)
        .pr(8)
        .py(6)
        .flex_none()
        .rounded(6)
        .items_center()
        .gap(8)
        .when(here, (el) => el.bg(t.selected))
        .cursor_pointer()
        .hover((s) => s.bg(t.hover))
        .on_click(() => run("pane.focus", { pane: g.pick.pane }))
        .child(div().w(12).flex_none().text_right().text_size(11).text_color(t.dim).child(n >= 1 && n <= 9 ? String(n) : ""))
        .child(div().w(3).h(30).flex_none().rounded(2).bg(fill))
        .child(v_flex().flex_1().min_w(0).gap(1)
          .child(h_flex().gap(6).items_center()
            .child(div().flex_1().min_w(0).truncate().font_medium().text_color(g.rank > RANK.idle ? t.foreground : t.muted).child(g.label))
            .child(div()
              .id(`open-${g.space}`)
              .h(18)
              .px(3)
              .gap(3)
              .flex()
              .items_center()
              .rounded(4)
              .text_size(11)
              .text_color(t.dim)
              .cursor_pointer()
              .tooltip("List agents")
              .hover((s) => s.bg(t.hover).text_color(t.foreground))
              .on_click((_e, cx) => {
                cx.stop_propagation();
                openOverlay({ mod: "matrix-agents", kind: "popup", width: 320, height: Math.min(460, 46 + 40 * g.members.length + 12), props: { spaceList: g.space } });
              })
              .child(String(g.members.length))
              .child(svg("mods/workspace-chrome/chevron-right.svg").size(11).flex_none()))
            .child(h_flex().w(14).flex_none().justify_center().child(this.status(t, { status: STATUS_OF[g.rank] }, true))))
          .child(h_flex().min_w(0).overflow_hidden().whitespace_nowrap().text_size(11.5).text_color(t.dim)
            .children(counts.flatMap((c, i) => [
              ...(i ? [div().flex_none().child(" \u00b7 ")] : []),
              div().flex_none().text_color(c.r === RANK.idle ? t.dim : (t[STATUS_OF[c.r]] ?? t.dim)).child(`${c.n} ${c.word}`),
            ]))));
    };

    // The rail: one line per space, its color and state.
    const railRow = (g, n) => h_flex()
      .id(`rail-${g.id}`)
      .h(26)
      .px(8)
      .flex_none()
      .items_center()
      .gap(4)
      .hover((s) => s.bg(t.hover))
      .on_click(() => run("pane.focus", { pane: g.pick.pane }))
      .child(div().flex_1().min_w(0).whitespace_nowrap().text_right().text_color(t.muted).child(String(n)))
      .child(div().w(3).h(14).flex_none().rounded(2).bg(spaceFill(t, g.space)))
      .child(h_flex().w(14).flex_none().items_center().justify_center().child(this.status(t, { status: STATUS_OF[g.rank] }, true)));

    const pinGroup = groups.find((g) => g.id === "pinned");
    const rows = bySpace
      ? collapsed
        ? [...pinned.flatMap(withKids), ...spaceGroups.map((g, i) => railRow(g, pinned.length + i + 1))]
        : [
            ...(pinGroup ? [header(pinGroup), ...(this.folded.has("pinned") ? [] : pinned.flatMap(withKids))] : []),
            ...spaceGroups.flatMap((g, i) => [spaceRow(g, pinned.length + i + 1)]),
          ]
      : collapsed
        ? list.flatMap(withKids)
        : groups.flatMap((g) => [header(g), ...(this.folded.has(g.id) ? [] : g.members.flatMap(withKids))]);

    return v_flex()
      .size_full()
      .min_h(0)
      .border_t(1)
      .border_color(t.border)
      .text_size(13)
      .when(!collapsed, (el) =>
        el.child(
          h_flex()
            .px(16)
            .h(41)
            .pt(14)
            .pb(5)
            .flex_none()
            .items_center()
            .justify_between()
            .child(div().text_size(11.5).font_medium().text_color(t.accent).child("AGENTS // ONLINE"))
            .child(
              div()
                .id("ag-sort")
                .text_size(11)
                .text_color(t.dim)
                .hover((s) => s.text_color(t.foreground))
                .on_click(() => openOverlay({ mod: "matrix-agents", kind: "popup", width: 200, height: 172, props: { sortMenu: true } }))
                .tooltip(`Sort agents: ${sort.label}`)
                .child(svg(`mods/workspace-chrome/${sort.icon}.svg`).size(14)),
            ),
        ),
      )
      .when(list.length === 0 && !collapsed, (el) =>
        el.child(div().px(12).text_size(12).text_color(t.dim).child("No agent status yet. Agents show up here when they report their status. Older versions and agents inside tmux may not.")),
      )
      .child(v_flex().id("ag-list").flex_1().min_h(0).px(collapsed ? 0 : 8).overflow_y_scrollbar().mode("always").children(rows))
      .when(collapsed, (el) =>
        el.child(
          h_flex()
            .h(28)
            .items_center()
            .justify_center()
            .child(
              div()
                .id("collapse")
                .text_size(13)
                .text_color(t.dim)
                .hover((s) => s.text_color(t.foreground))
                .on_click(toggleSidebar)
                .child("»"),
            ),
        ),
      );
  }
}
