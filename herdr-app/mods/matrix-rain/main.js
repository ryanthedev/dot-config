import { View, div } from "gpui-kit";

// Matrix rain drawn with native `.frames` only: no timers, no re-renders.
// Every cell has three stacked layers (head, near trail, far trail). Each layer's
// frame list says, step by step, whether the falling streak covers that cell.
// All cells in a column share one `ms`, so the shared clock keeps them in step.

const GLYPHS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789Z:=*+-<>";
const CELL_W = 14;
const CELL_H = 18;
const HEAD = "#d8ffe0";
const NEAR = "#3dff6e";
const FAR = "#0f8a34";

function pick(rand) {
  return GLYPHS[Math.floor(rand() * GLYPHS.length)];
}

// Small seeded random so a column keeps its look across re-renders.
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function buildColumn(c, rows) {
  const rand = rng(c * 7919 + rows * 31 + 1);
  const trail = 6 + Math.floor(rand() * 10);
  const near = 4;
  // Two streaks per column, half a cycle apart, so the strip never sits empty.
  const length = Math.ceil(rows * 0.6) + trail + Math.floor(rand() * rows * 0.4);
  const start = Math.floor(rand() * length);
  const ms = 55 + Math.floor(rand() * 70);
  const cells = [];
  for (let r = 0; r < rows; r++) {
    const head = [], nearL = [], farL = [];
    for (let k = 0; k < length; k++) {
      // How far above the nearest streak head this row is at step k.
      let d = Infinity;
      for (const off of [0, Math.floor(length / 2)]) {
        const pos = (k + start + off) % length;
        if (pos >= r) d = Math.min(d, pos - r);
      }
      const g = pick(rand);
      head.push(d === 0 ? g : " ");
      nearL.push(d > 0 && d <= near ? g : " ");
      farL.push(d > near && d <= trail ? g : " ");
    }
    cells.push({ head, near: nearL, far: farL });
  }
  return { ms, cells };
}

export default class MatrixRain extends View {
  init() {
    this.size = null;
    this.cols = [];
  }

  layoutFor(size) {
    const cols = Math.max(1, Math.floor(size.width / CELL_W));
    const rows = Math.max(1, Math.ceil(size.height / CELL_H));
    if (this.key === `${cols}x${rows}`) return;
    this.key = `${cols}x${rows}`;
    this.cols = Array.from({ length: cols }, (_, c) => buildColumn(c, rows));
  }

  render() {
    const layer = (id, list, color, ms) =>
      div().id(id).absolute().top(0).left(0).w(CELL_W).h(CELL_H)
        .flex().justify_center().text_color(color)
        .child(list[0]).frames(list, ms);

    return div().id("root").size_full().overflow_hidden().bg("#000000")
      .flex().flex_row().justify_center()
      .text_size(14).line_height(CELL_H)
      .on_size_change((size, cx) => {
        this.size = size;
        this.layoutFor(size);
        cx.notify();
      })
      .children(this.cols.map((col, c) =>
        div().w(CELL_W).flex().flex_col().children(col.cells.map((cell, r) =>
          div().relative().w(CELL_W).h(CELL_H)
            .child(layer(`f${c}-${r}`, cell.far, FAR, col.ms))
            .child(layer(`n${c}-${r}`, cell.near, NEAR, col.ms))
            .child(layer(`h${c}-${r}`, cell.head, HEAD, col.ms))))));
  }
}
