// Prefix key, herdr-TUI style. ctrl-space (keys.json: "mod.open:leader") opens
// this popup; the next key runs one command and closes it. Esc, ctrl-space or
// any unbound key just closes it. The table mirrors ~/.config/herdr/config.toml.

import { View, div } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { run, props, closeOverlay, openOverlay, focused, panes, theme, home } from "herdr";

const HOME = home();
const split = (argv) => () => run("pane.split", { direction: "right", argv });
const worktree = (action, width, height) => () => {
  const f = focused();
  openOverlay({ mod: "worktree", kind: "dialog", width, height,
    props: { space: f?.space, folder: panes().find((p) => p.focused)?.cwd, action } });
};

// Scrollback in nvim: Herdr does no work here. The popup only splits a pane
// running nvim, and nvim itself runs `hc read` (no shell, no temp file), so
// the window never waits on the read.
function scrollback() {
  const t = focused()?.terminal;
  if (!t) return;
  // Async, two reads: the screen alone (`hc read t`, ~0.03 s) shows at once,
  // then the full history (`--lines 3000`, seconds when an agent is idle)
  // replaces it when it arrives, unless it came back shorter.
  const lua = "local b=vim.api.nvim_get_current_buf() local n=0" +
    " vim.api.nvim_buf_set_lines(b,0,-1,false,{'loading scrollback for " + t + "...'})" +
    " local function fill(r) vim.schedule(function() if not vim.api.nvim_buf_is_valid(b) then return end" +
    " local L=vim.tbl_filter(function(l) return not l:find('^%[hc%] ') end, vim.split(r.stdout or '','\\n',{plain=true}))" +
    " if #L<n then return end n=#L" +
    " vim.api.nvim_buf_set_lines(b,0,-1,false,L) vim.bo[b].modified=false" +
    " if vim.api.nvim_get_current_buf()==b then vim.cmd('normal! G') end end) end" +
    " local hc='" + HOME + "/.local/bin/hc'" +
    " vim.system({hc,'read','" + t + "'},{text=true},fill)" +
    " vim.system({hc,'read','" + t + "','--lines','3000'},{text=true},fill)";
  run("pane.split", { direction: "right", argv: ["/bin/zsh", "-lc", 'exec nvim "$@"', "nvim",
    "+lua " + lua,
    "+setlocal number buftype=nofile bufhidden=wipe noswapfile nomodified",
    "+nnoremap <buffer> q :q!<CR>", "+normal! G"] });
}

// [key, label, action]. Keys are spelled as `keystroke` reports them.
const GROUPS = [
  ["Panes", [
    ["h j k l", "focus", null],
    ["v", "split right", () => run("pane.split", { direction: "right" })],
    ["-", "split down", () => run("pane.split", { direction: "down" })],
    ["z", "zoom", () => run("pane.zoom")],
    ["x", "close pane", () => run("pane.close")],
    ["e", "scrollback in nvim", scrollback],
  ]],
  ["Tabs", [
    ["c", "new tab", () => run("tab.new")],
    ["n / p", "next / prev", null],
    ["1-9", "go to tab", null],
    ["T", "rename tab", () => run("tab.rename")],
    ["X", "close tab", () => run("tab.close")],
  ]],
  ["Spaces", [
    ["J / K", "next / prev", null],
    ["⇧1-9", "go to space", null],
    ["w / g", "picker", () => run("mod.open", { name: "picker" })],
    ["N", "new space", () => run("space.new")],
    ["W", "rename space", () => run("space.rename")],
    ["D", "close space", () => run("space.close")],
  ]],
  ["Agents & more", [
    ["a / A", "next / prev agent", null],
    ["G O E", "worktree new/open/rm", null],
    ["L", "lazygit", split(["lazygit"])],
    ["C", "clock", split([`${HOME}/.config/herdr/scripts/clock.sh`])],
    ["b", "sidebar", () => run("layout.toggle", { id: "sidebar" })],
    ["s", "settings", () => run("app.settings")],
    ["H / ?", "help", () => run("app.help")],
  ]],
];

const SHIFT_DIGITS = { "!": 1, "@": 2, "#": 3, $: 4, "%": 5, "^": 6, "&": 7, "*": 8, "(": 9 };

function actionFor(e) {
  const m = e.modifiers;
  if (m.control || m.platform || m.alt) return null;
  const k = e.key;
  const ch = e.key_char ?? "";
  if (SHIFT_DIGITS[ch]) return () => run("space.select", { index: SHIFT_DIGITS[ch] });
  if (/^[1-9]$/.test(k)) {
    const index = Number(k);
    return m.shift ? () => run("space.select", { index }) : () => run("tab.select", { index });
  }
  const key = m.shift && /^[a-z]$/.test(k) ? k.toUpperCase() : (ch && !/^[a-z]$/i.test(ch) ? ch : k);
  const table = {
    h: () => run("pane.go", { direction: "left" }),
    j: () => run("pane.go", { direction: "down" }),
    k: () => run("pane.go", { direction: "up" }),
    l: () => run("pane.go", { direction: "right" }),
    n: () => run("tab.next"),
    p: () => run("tab.prev"),
    J: () => run("space.next"),
    K: () => run("space.prev"),
    a: () => run("agent.next"),
    A: () => run("agent.prev"),
    w: () => run("mod.open", { name: "picker" }),
    g: () => run("mod.open", { name: "picker" }),
    G: worktree("new", 460, 280),
    O: worktree("open", 560, 480),
    E: worktree("remove", 440, 260),
    H: () => run("app.help"),
    "?": () => run("app.help"),
    "-": () => run("pane.split", { direction: "down" }),
    minus: () => run("pane.split", { direction: "down" }),
  };
  if (table[key]) return table[key];
  for (const [, rows] of GROUPS) for (const [label, , fn] of rows) if (fn && label === key) return fn;
  return null;
}

export default class Leader extends View {
  init(_props, cx) {
    this.handle = cx.focus_handle();
    this.handle.focus();
  }

  render(cx) {
    const t = theme();
    const close = () => closeOverlay(props().overlay);
    const row = ([key, label]) =>
      h_flex().gap(8).items_center()
        .child(div().w(52).text_color(t.accent).font_semibold().child(key))
        .child(div().text_color(t.muted).truncate().child(label));
    return v_flex()
      .id("leader")
      .track_focus(this.handle)
      .on_key_down((e, cx) => {
        cx.stop_propagation();
        if (["shift", "control", "alt", "platform", "function"].includes(e.key)) return;
        const fn = actionFor(e);
        close();
        if (fn) fn();
      })
      .size_full().p(14).gap(10).bg(t.popover).text_size(13)
      .child(h_flex().justify_between()
        .child(div().font_semibold().text_color(t.foreground).child("ctrl-space"))
        .child(div().text_size(11).text_color(t.dim).child("Esc to cancel")))
      .child(h_flex().gap(18).items_start().children(
        GROUPS.map(([title, rows]) =>
          v_flex().flex_1().gap(4)
            .child(div().text_size(11).text_color(t.dim).child(title))
            .children(rows.map(row)))));
  }
}
