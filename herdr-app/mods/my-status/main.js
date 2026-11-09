import { View, div, svg } from "gpui-kit";
import { h_flex } from "gpui-base";
import { spaces, agents, panes, focused, exec, shared, theme, run, window, keys, appHome, readTextFile, writeTextFile, layout } from "herdr";

// Same ground as the terminals: the theme background at the layout's terminal_opacity.
const glass = (c) => {
  // Terminals stack two layers at that opacity (measured 2026-11-09), so match their combined cover.
  const op = Math.max(0, Math.min(1, Number(layout()?.terminal_opacity ?? 1))), a = 1 - (1 - op) ** 2;
  return /^#[0-9a-f]{6}$/i.test(c ?? "") ? c + Math.round(a * 255).toString(16).padStart(2, "0") : c;
};

// Status bar for the shown space: where you are (space, folder, branch and its
// git state), its tabs, and its agents by status, plus anyone elsewhere who
// needs you.
//
// my-status (cloned from workspace-status): also shows Herdr's notifications
// ("Claude Code finished") on the left for NOTE_MS instead of as a toast.
// Herdr has no setting for that and restores its own `toast` mod on every
// start, so init() rewrites mods/toast/main.js each time: the patched toast
// hands its text to shared("status.toast") and closes itself at once.
// Herdr then keeps a copy of the edited one as mods/toast-edited*, which
// init() deletes.
//
// Cost: herdr data (spaces, agents) re-renders this for free when it changes.
// Git is the only polled thing: one read-only `git status` every GIT_MS, or at
// once when the focused folder changes. The 2-second tick only does cheap JS
// and redraws just when what the bar shows actually changed.

const TICK_MS = 2000;
const NOTE_MS = 10000;
const NOTE_KEY = "status.toast";

const TOAST_SRC = `// Patched by mods/my-status at every start: hands the notification to the
// status bar (shared "status.toast") instead of popping up. Herdr restores its
// own version on start; my-status writes this one back.
import { View, div } from "gpui-kit";
import { props, closeOverlay, setShared } from "herdr";

export default class Toast extends View {
  init(_props, cx) {
    const p = props() ?? {};
    setShared("${NOTE_KEY}", { title: p.title ?? "", body: p.body ?? "", level: p.level ?? "info", action: p.action ?? null, at: Date.now() });
    if (p.overlay) closeOverlay(p.overlay);
  }

  render() {
    return div();
  }
}
`;

async function patchToast() {
  const home = appHome();
  const path = `${home}/mods/toast/main.js`;
  try {
    const cur = await readTextFile(path);
    if (cur !== null && cur !== TOAST_SRC) await writeTextFile(path, TOAST_SRC, cur);
  } catch (e) { console.log(`my-status: could not patch the toast mod: ${e}`); }
  try {
    await exec("/bin/sh", ["-c", 'rm -rf "$1"/mods/toast-edited*', "sh", home], { timeout: 5000 });
  } catch { /* nothing to tidy */ }
}

// The latest notification, while it is still fresh.
function note() {
  const n = shared(NOTE_KEY);
  return n && Date.now() - (n.at ?? 0) < NOTE_MS ? n : null;
}
const GIT_MS = 6000;
// Reads write nothing under .git (no index refresh or lock, no fsmonitor cookie).
const READ = ["--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "diff.autoRefreshIndex=false"];

function where() {
  const space = spaces().find((s) => s.active), f = focused();
  const pane = f?.pane ? panes().find((p) => p.pane === f.pane) : null;
  const on = f?.pane === null ? (f.terminal?.includes("/") ? f.terminal.split("/")[0] : null) : space?.machine ?? null;
  return { space, cwd: pane?.cwd || f?.cwd || space?.folder || null, on };
}

const tilde = (p) => p ? p.replace(/^\/(Users|home)\/[^/]+(?=\/|$)/, "~") : "";
const short = (p) => {
  const parts = tilde(p).split("/");
  return parts.length > 4 ? `${parts[0]}/…/${parts.slice(-2).join("/")}` : parts.join("/");
};
const ago = (ms) => {
  const m = Math.floor(ms / 60000);
  return m < 1 ? "<1m" : m < 60 ? `${m}m` : `${Math.floor(m / 60)}h${m % 60 ? `${m % 60}m` : ""}`;
};

// `git status --porcelain=v2 --branch`: branch, upstream distance, file counts.
function parseGit(out) {
  const g = { head: null, ahead: 0, behind: 0, upstream: false, staged: 0, changed: 0, untracked: 0, conflicts: 0 };
  for (const line of out.split("\n")) {
    if (line.startsWith("# branch.head ")) g.head = line.slice(14);
    else if (line.startsWith("# branch.upstream ")) g.upstream = true;
    else if (line.startsWith("# branch.ab ")) {
      const m = /\+(\d+) -(\d+)/.exec(line);
      if (m) { g.ahead = +m[1]; g.behind = +m[2]; }
    } else if (line.startsWith("? ")) g.untracked++;
    else if (line.startsWith("u ")) g.conflicts++;
    else if (line.startsWith("1 ") || line.startsWith("2 ")) {
      const xy = line.slice(2, 4);
      if (xy[0] !== ".") g.staged++;
      if (xy[1] !== ".") g.changed++;
    }
  }
  return g;
}

export default class WorkspaceStatus extends View {
  init(_props, cx) {
    this.git = null; this.gitKey = null; this.gitAt = 0; this.shown = "";
    this.noteAt = 0;
    this.tick(cx);
    cx.timer.every(TICK_MS, (cx) => this.tick(cx));
    cx.timer.every(1000, (cx) => this.expireNote(cx));
    cx.spawn(async () => { await patchToast(); });
  }

  tick(cx) {
    const { cwd, on } = where();
    const key = `${on ?? ""}|${cwd ?? ""}`;
    const now = Date.now();
    if (key !== this.gitKey || now - this.gitAt >= GIT_MS) this.refreshGit(key, cwd, on, cx);
    // Durations shown in the bar change on their own; redraw only when one does.
    const shown = this.clockText();
    if (shown !== this.shown) { this.shown = shown; cx.notify(); }
  }

  refreshGit(key, cwd, on, cx) {
    if (this.loading) return;
    if (key !== this.gitKey) { this.gitKey = key; this.git = null; }
    this.gitAt = Date.now();
    if (!cwd) return;
    this.loading = true;
    cx.spawn(async (cx) => {
      let git = null;
      try {
        const r = await exec("git", [...READ, "status", "--porcelain=v2", "--branch", "--untracked-files=normal"], { cwd, on, timeout: 5000 });
        if (r.code === 0) git = parseGit(r.stdout);
      } catch { git = null; }
      finally { this.loading = false; }
      if (this.gitKey !== key) return;
      if (JSON.stringify(git) !== JSON.stringify(this.git)) { this.git = git; cx.notify(); }
    });
  }

  // A note drawn by render() goes once it is NOTE_MS old.
  expireNote(cx) {
    const shownAt = note()?.at ?? 0;
    if (shownAt !== this.noteAt) { this.noteAt = shownAt; cx.notify(); }
  }

  // The space's longest-running work, as text, so tick() can compare it.
  clockText() {
    const space = spaces().find((s) => s.active);
    const since = (space?.tabs ?? []).map((t) => t.working_since).filter(Boolean);
    return since.length ? ago(Date.now() - Math.min(...since)) : "";
  }

  // The palette key as actually bound, not a hardcoded one; without a
  // binding the hint stays useful ("commands") instead of lying.
  hint() {
    const mac = window()?.platform === "macos";
    const mod = { cmd: mac ? "⌘" : "Ctrl+", ctrl: mac ? "⌃" : "Ctrl+", shift: mac ? "⇧" : "Shift+", alt: mac ? "⌥" : "Alt+", option: mac ? "⌥" : "Alt+" };
    const b = keys().find((k) => k.section === "global" && k.action === "app.palette");
    const parts = b && b.keys.endsWith("--") ? [...b.keys.slice(0, -2).split("-"), "-"] : b?.keys.split("-");
    const key = parts && parts.map((p) => mod[p.toLowerCase()] ?? p.toUpperCase()).join("");
    return key ? `${key}  commands` : "commands";
  }

  render() {
    const t = theme();
    const { space, cwd } = where();
    const all = agents();
    const mine = all.filter((a) => a.space === space?.id);
    const count = (s) => mine.filter((a) => a.status === s).length;
    const elsewhere = all.filter((a) => a.space !== space?.id && a.status === "blocked").length;
    const color = t[shared("space.colors")?.[space?.id]] ?? t.accent;
    const tab = space?.tabs.find((x) => x.active);
    const git = this.git;
    const branch = git?.head && git.head !== "(detached)" ? git.head : space?.branch;

    const sep = () => div().w(1).h(12).bg(t.border);
    const icon = (name) => svg(`mods/workspace-chrome/${name}.svg`).size(13).flex_none();
    const item = (name, ...kids) => h_flex().gap(5).items_center().flex_none().child(icon(name)).children(kids);
    const dot = (c) => div().size(6).rounded(3).bg(c).flex_none();
    const stat = (n, c, text) => n > 0 ? h_flex().gap(4).items_center().text_color(c).child(dot(c)).child(`${n} ${text}`) : null;

    const gitBits = git ? [
      git.ahead ? div().text_color(t.success ?? t.foreground).child(`↑${git.ahead}`) : null,
      git.behind ? div().text_color(t.blocked).child(`↓${git.behind}`) : null,
      git.conflicts ? div().text_color(t.removed ?? t.blocked).child(`${git.conflicts} conflict${git.conflicts > 1 ? "s" : ""}`) : null,
      git.staged ? div().text_color(t.success ?? t.foreground).child(`${git.staged} staged`) : null,
      git.changed ? div().text_color(t.working).child(`${git.changed} changed`) : null,
      git.untracked ? div().text_color(t.dim).child(`${git.untracked} new`) : null,
      !git.staged && !git.changed && !git.untracked && !git.conflicts ? div().text_color(t.dim).child("clean") : null,
    ].filter(Boolean) : [];

    const agentBits = [
      stat(count("blocked"), t.blocked, "needs you"),
      stat(count("working"), t.working, this.shown ? `working · ${this.shown}` : "working"),
      stat(count("done"), t.done, "done"),
      stat(count("idle"), t.dim, "idle"),
    ].filter(Boolean);

    const n = note();
    const NOTE_DOT = { error: t.blocked, warning: t.working, success: t.done, info: t.accent };
    const noteBit = n ? h_flex().id("note").gap(6).items_center().flex_none().cursor_pointer()
      .on_click(() => { if (n.action?.name) run(n.action.name, n.action.args ?? {}); })
      .child(dot(NOTE_DOT[n.level] ?? t.accent))
      .child(div().text_color(t.foreground).child(n.title))
      .when(Boolean(n.body), (el) => el.child(div().text_color(t.dim).child(n.body))) : null;

    return h_flex().size_full().px(14).gap(12).items_center().overflow_hidden().whitespace_nowrap()
      .bg(glass(t.background)).border_t(1).border_color(t.border).text_size(11.8).text_color(t.muted)
      // Herdr's latest notification, in place of its toast.
      .when(Boolean(noteBit), (el) => el.child(noteBit).child(sep()))
      // Where: space, machine, folder.
      .child(h_flex().gap(6).items_center().flex_none().child(dot(color))
        .child(div().text_color(t.foreground).child(space?.name ?? "—")))
      .when(Boolean(space?.machine), (el) => el.child(item("server", space.machine)))
      .when(Boolean(cwd), (el) => el.child(item("folder", short(cwd))))
      // Branch and git state.
      .when(Boolean(branch), (el) => el.child(sep()).child(item("git-branch", div().text_color(t.foreground).child(branch), ...gitBits)))
      // Tabs.
      .when((space?.tabs.length ?? 0) > 0, (el) => el.child(sep()).child(item("layers",
        `tab ${tab?.index ?? "?"}/${space.tabs.length}`,
        ...(tab?.named ? [div().text_color(t.foreground).child(tab.name)] : []))))
      // This space's agents.
      .child(sep())
      .child(mine.length
        ? h_flex().gap(10).items_center().flex_none().children(agentBits)
        : div().text_color(t.dim).child("no agents"))
      .child(div().flex_1())
      .when(elsewhere > 0, (el) => el.child(h_flex().gap(4).items_center().flex_none().text_color(t.blocked)
        .child(dot(t.blocked)).child(`${elsewhere} need${elsewhere > 1 ? "" : "s"} you elsewhere`)))
      .child(div().id("palette").flex_none().text_color(t.dim).on_click(() => run("app.palette")).child(this.hint()));
  }
}
