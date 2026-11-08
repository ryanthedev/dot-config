// Fleet board, docked beside the work area (layouts/matrix.json, block "fleet"):
// an ops console of every space with agents, each a section of cards, most
// urgent first; a space with many agents wraps its cards into rows.
//
// It never moves the window by itself (no agent.focus from render: that loops,
// since looking at a done agent re-sorts the list). A click or Enter goes there.
// keys.json (layout:matrix): cmd-g sends "keys", which gives the board the
// keyboard; Esc hands it back. ? shows the key sheet.

import { View, div, svg, image } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { agents, spaces, focused, run, theme, shared, settings, nextCommand } from "herdr";

const URGENT = { blocked: 4, done: 3, working: 2, idle: 1 };
const LABEL = { blocked: "NEEDS YOU", done: "DONE", working: "WORKING", idle: "IDLE" };
const ORDER = ["blocked", "working", "done", "idle"];
// Space colors as matrix-spaces draws them (shared "space.colors").
const MARK = { ansi6: "#22a99a", ansi3: "#e3814f", ansi4: "#5b8def", ansi5: "#8b7cf6", ansi2: "#3fae6a", ansi1: "#d9649a" };
const fillOf = (t, id) => {
  const c = (shared("space.colors") ?? {})[id] ?? "ansi6";
  return c.startsWith("#") ? c : (MARK[c] ?? t[c] ?? t.dim);
};
const tone = (t, st) => (st === "idle" ? (t.idle ?? t.dim) : (t[st] ?? t.dim));
const clean = (s) => (s ?? "").replace(/^[^\p{L}\p{N}]+/u, "").trim();
const pad2 = (n) => String(n).padStart(2, "0");

const KEYS = [
  ["cmd-g", "take the keyboard"],
  ["↑ ↓ ← →", "move (or h j k l)"],
  ["tab", "next space (shift: back)"],
  ["] [", "next / previous space"],
  ["1\u20139", "jump to space"],
  ["enter", "go to agent"],
  ["click", "go to agent"],
  ["esc", "back to your pane"],
  ["?", "this sheet"],
];

// What an agent is doing: its own title when that says something, else its tab.
function taskOf(a) {
  const prog = a.program?.name ?? "";
  const own = clean(a.title);
  const telling = own && own.toLowerCase() !== prog.toLowerCase() && own.toLowerCase() !== a.program?.key && !/^[~/]/.test(own);
  return telling ? own : (a.tab_name && !/^\d+$/.test(a.tab_name) ? a.tab_name : prog || a.address);
}

function duration(ms) {
  const m = Math.floor(ms / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

// The agent's icon from the app's program table: a one-color glyph or a picture.
function progIcon(p, size, color) {
  if (!p?.icon) return null;
  return p.tint ? svg(p.icon).size(size).flex_none().text_color(color) : image(p.icon).w(size).h(size).flex_none();
}

// Sections: every space, in sidebar order (shell-only spaces get a dim line);
// cards most urgent first, then tab order, so a card only moves when its state does.
function sections() {
  const all = agents();
  return spaces()
    .map((s) => ({
      space: s,
      cards: all.filter((a) => a.space === s.id).sort((x, y) => (URGENT[y.status] ?? 0) - (URGENT[x.status] ?? 0) || (x.tab_index ?? 0) - (y.tab_index ?? 0)),
    }));
}

export default class Fleet extends View {
  init(_props, cx) {
    this.handle = cx.focus_handle();
    this.sel = null; // the highlighted card, by address: survives re-sorts
    this.from = null;
    this.help = false;
    // When each agent's state last changed (done and idle count as one).
    try { this.changed = JSON.parse(localStorage.getItem("changed") ?? "{}"); } catch { this.changed = {}; }
    cx.timer.every(30000, (cx) => cx.notify());
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        if (c !== "keys") continue;
        this.from = focused()?.pane ?? null;
        this.sel = focused()?.agent ?? this.sel;
        this.handle.focus();
        cx.notify();
      }
    });
  }

  track(list, now) {
    let dirty = false;
    for (const a of list) {
      const s = a.status === "done" ? "idle" : a.status;
      if (this.changed[a.address]?.s === s) continue;
      this.changed[a.address] = { s, at: now };
      dirty = true;
    }
    if (!dirty) return;
    const live = new Set(list.map((a) => a.address));
    for (const [k, c] of Object.entries(this.changed)) if (!live.has(k) && now - c.at > 7 * 86400000) delete this.changed[k];
    try { localStorage.setItem("changed", JSON.stringify(this.changed)); } catch {}
  }

  go(a) {
    if (!a) return;
    this.from = null;
    this.help = false;
    run("pane.focus", { pane: a.pane });
  }

  back() {
    const from = this.from;
    this.from = null;
    if (from) run("pane.focus", { pane: from });
  }

  render(cx) {
    const t = theme();
    const mono = settings().font ?? settings().font_family ?? "monospace";
    const now = Date.now();
    const secs = sections();
    const flat = secs.flatMap((s) => s.cards);
    this.track(flat, now);
    const kbd = this.handle.is_focused();
    if (!flat.some((a) => a.address === this.sel)) this.sel = flat[0]?.address ?? null;
    const at = flat.findIndex((a) => a.address === this.sel);
    const secOf = (addr) => secs.findIndex((s) => s.cards.some((a) => a.address === addr));
    const here = focused()?.agent;
    const count = Object.fromEntries(ORDER.map((st) => [st, flat.filter((a) => a.status === st).length]));

    // ── header: title, a blinking cursor, the stat tiles and a state bar ──
    const tile = (st) => {
      const n = count[st];
      const hot = st === "blocked" && n > 0;
      return v_flex()
        .id(`tile-${st}`)
        .flex_1()
        .min_w(0)
        .px(10)
        .py(7)
        .gap(2)
        .rounded(6)
        .border(1)
        .border_color(n ? tone(t, st) + (hot ? "aa" : "40") : t.border)
        .bg(n ? tone(t, st) + (hot ? "1f" : "0d") : "#00000000")
        .when(hot, (el) => el.loop("opacity", { from: 0.55, to: 1, period: 1400 }))
        .child(div().font_family(mono).text_size(22).font_semibold().text_color(n ? tone(t, st) : t.dim).child(pad2(n)))
        .child(div().font_family(mono).text_size(9.5).text_color(n ? tone(t, st) : t.dim).child(LABEL[st]));
    };
    const bar = h_flex().h(3).w_full().rounded(2).overflow_hidden().bg(t.border)
      .children(ORDER.filter((st) => count[st]).map((st) => div().h_full().flex_grow(count[st]).flex_basis(0).bg(tone(t, st))
        .when(st === "working", (el) => el.loop("opacity", { from: 0.5, to: 1, period: 1600 }))));
    const helpBtn = div()
      .id("fleet-help")
      .size(22)
      .flex_none()
      .rounded(11)
      .border(1)
      .border_color(this.help ? t.accent : t.border)
      .text_color(this.help ? t.accent : t.dim)
      .font_family(mono)
      .text_size(12)
      .flex()
      .items_center()
      .justify_center()
      .cursor_pointer()
      .hover((s) => s.border_color(t.accent).text_color(t.accent))
      .tooltip("Keys (?)")
      .on_click((_e, cx) => {
        this.help = !this.help;
        cx.notify();
      })
      .child("?");
    const header = v_flex().px(16).pt(14).pb(12).gap(12).flex_none()
      .child(h_flex().items_center().gap(10)
        .child(h_flex().font_family(mono).text_size(13).font_semibold().text_color(t.accent)
          .child("FLEET//CTRL")
          .child(div().frames(["█", " "], 530)))
        .child(div().flex_1().font_family(mono).text_size(11).text_color(t.dim)
          .child(`${pad2(secs.length)} SPACES · ${pad2(flat.length)} AGENTS`))
        .child(div().font_family(mono).text_size(10.5).text_color(kbd ? t.accent : t.dim).child(kbd ? "◉ KEYS" : "cmd-g"))
        .child(helpBtn))
      .child(h_flex().gap(8).children(ORDER.map(tile)))
      .child(bar);

    // ── a card: status stripe, icon + task, mono metadata ──
    const card = (a) => {
      const on = kbd && a.address === this.sel;
      const current = a.address === here;
      const c = tone(t, a.status);
      const since = this.changed[a.address]?.at;
      const tab = a.tab_name && !/^\d+$/.test(a.tab_name) ? a.tab_name : `T${a.tab_index ?? "?"}`;
      return h_flex()
        .id(`card-${a.address}`)
        .w(250)
        .flex_none()
        .rounded(6)
        .overflow_hidden()
        .border(1)
        .border_color(on ? t.accent : a.status === "blocked" ? c + "99" : current ? t.accent + "55" : t.border)
        .bg(on ? t.accent + "14" : current ? t.selected : t.background)
        .when(on, (el) => el.shadow_md())
        .when(a.status === "blocked" && !on, (el) => el.loop("opacity", { from: 0.7, to: 1, period: 1400 }))
        .cursor_pointer()
        .hover((s) => s.border_color(t.accent + "aa"))
        .on_click(() => this.go(a))
        // The stripe: the agent's state at a glance; working breathes.
        .child(div().w(3).self_stretch().flex_none().bg(c)
          .when(a.status === "working", (el) => el.loop("opacity", { from: 0.35, to: 1, period: 1200 }))
          .when(a.status === "idle", (el) => el.opacity(0.35)))
        .child(v_flex().flex_1().min_w(0).pl(9).pr(10).py(8).gap(4)
          .child(h_flex().gap(7).items_center()
            .child(progIcon(a.program, 13, a.status === "idle" ? t.dim : t.muted) ?? div())
            .child(div().flex_1().min_w(0).truncate().font_medium().text_color(a.status === "idle" ? t.muted : t.foreground).child(taskOf(a)))
            // Animated icons draw over the key sheet, so they rest while it's open.
            .when(a.status === "working" && !this.help, (el) => el.child(svg("mods/workspace-chrome/spinner.svg").size(11).flex_none().text_color(c).spin(900)))
            .when(on, (el) => el.child(div().font_family(mono).text_size(11).text_color(t.accent).child("▸"))))
          .child(h_flex().gap(6).font_family(mono).text_size(10).items_center()
            .child(div().text_color(c).child(LABEL[a.status]))
            .child(div().text_color(t.dim).child("·"))
            .child(div().min_w(0).truncate().text_color(t.dim).child(tab))
            .child(div().flex_1())
            .when(Boolean(since), (el) => el.child(div().flex_none().text_color(t.dim).child(duration(now - since))))));
    };

    // ── a space: color tab, name, a rule in its color, its counts ──
    const section = (s, i) => {
      const fill = fillOf(t, s.space.id);
      const live = s.cards.filter((a) => a.status !== "idle").length;
      const hot = s.cards.some((a) => a.status === "blocked");
      const tabs = s.space.tabs ?? [];
      const panes = tabs.reduce((n, tb) => n + (tb.panes ?? 0), 0);
      const shells = div()
        .id(`shells-${s.space.id}`)
        .px(10)
        .py(6)
        .rounded(4)
        .border(1)
        .border_color(t.border)
        .font_family(mono)
        .text_size(10)
        .text_color(t.dim)
        .cursor_pointer()
        .hover((el) => el.text_color(t.foreground).border_color(fill))
        .on_click(() => run("space.select", { id: s.space.id }))
        .child(`// NO AGENTS · ${tabs.length} TAB${tabs.length === 1 ? "" : "S"} · ${panes} PANE${panes === 1 ? "" : "S"}${s.space.folder ? ` · ${s.space.folder}` : ""}`);
      return v_flex()
        .id(`sec-${s.space.id}`)
        .flex_none()
        .gap(8)
        .child(h_flex().gap(8).items_center()
          .child(div().font_family(mono).text_size(10).text_color(t.dim).child(pad2(i + 1)))
          .child(div().w(8).h(8).rounded(2).flex_none().bg(fill))
          .child(div().flex_none().max_w(260).truncate().font_family(mono).text_size(12).font_semibold().text_color(t.foreground).child(s.space.name.toUpperCase()))
          .child(div().flex_1().h(1).bg(fill + "40"))
          .child(div().flex_none().font_family(mono).text_size(10).text_color(hot ? t.blocked : live ? t.foreground : t.dim)
            .child(s.cards.length ? `${pad2(live)}/${pad2(s.cards.length)} LIVE` : "SHELLS")))
        .child(s.cards.length ? h_flex().flex_wrap().gap(8).children(s.cards.map(card)) : shells);
    };

    // ── the key sheet, over the board ──
    const sheet = v_flex()
      .id("fleet-sheet")
      .absolute()
      .top(0)
      .left(0)
      .right(0)
      .bottom(0)
      .bg(t.background + "e6")
      .items_center()
      .justify_center()
      .on_click((_e, cx) => {
        this.help = false;
        cx.notify();
      })
      .child(v_flex().w(380).p(18).gap(10).rounded(10).border(1).border_color(t.accent + "88").bg(t.popover).shadow_lg()
        .child(h_flex().items_center()
          .child(div().flex_1().font_family(mono).text_size(12).font_semibold().text_color(t.accent).child("KEYS//FLEET"))
          .child(div().font_family(mono).text_size(10).text_color(t.dim).child("? or esc to close")))
        .child(div().h(1).bg(t.border))
        .children(KEYS.map(([k, what]) => h_flex().gap(12).items_center()
          .child(h_flex().w(120).flex_none().gap(4)
            .children(k.split(" ").map((part) => div().px(6).h(20).rounded(4).border(1).border_color(t.border).bg(t.background)
              .font_family(mono).text_size(11).text_color(t.foreground).flex().items_center().child(part))))
          .child(div().flex_1().text_size(12.5).text_color(t.muted).child(what)))));

    return v_flex()
      .id("fleet")
      .relative()
      .track_focus(this.handle)
      .size_full()
      .min_h(0)
      .text_size(13)
      .on_key_down((e, cx) => {
        const k = e.key;
        const move = (i) => {
          if (flat.length) this.sel = flat[(i + flat.length) % flat.length].address;
        };
        const jump = (d) => {
          const live = secs.filter((s) => s.cards.length);
          if (!live.length) return;
          const si = Math.max(0, live.findIndex((s) => s.cards.some((a) => a.address === this.sel)));
          this.sel = live[(si + d + live.length) % live.length].cards[0].address;
        };
        if (k === "?" || (k === "/" && e.modifiers?.shift)) this.help = !this.help;
        else if (k === "escape" && this.help) this.help = false;
        else if (k === "escape") return this.back();
        else if (k === "enter") return this.go(flat[at]);
        else if (k === "down" || k === "j" || k === "right" || k === "l") move(at + 1);
        else if (k === "up" || k === "k" || k === "left" || k === "h") move(at - 1);
        else if (k === "tab" && e.modifiers?.shift) jump(-1);
        else if (k === "tab" || k === "]") jump(1);
        else if (k === "[") jump(-1);
        else if (/^[1-9]$/.test(k) && secs[+k - 1]) {
          const s = secs[+k - 1];
          if (!s.cards.length) return run("space.select", { id: s.space.id });
          this.sel = s.cards[0].address;
        }
        else return;
        cx.stop_propagation();
        cx.notify();
      })
      .child(header)
      .child(div().h(1).flex_none().bg(t.accent + "33"))
      .when(flat.length === 0, (el) => el.child(div().px(16).py(12).font_family(mono).text_size(11).text_color(t.dim).child("// NO AGENTS ONLINE")))
      .child(v_flex().id("fleet-list").flex_1().min_h(0).px(16).pt(14).pb(16).gap(18).overflow_y_scrollbar()
        .children(secs.map(section)))
      .when(this.help, (el) => el.child(sheet));
  }
}
