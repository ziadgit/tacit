# Glyphs

Every drawing in tacit is made of three marks on one grid: a dot, a dash and a plus (a bold plus marks a centre).

- Draw on a canvas with `Tacit.pen(canvas, cell)` and `put(x, y, v)`: `v` under 0.3 is a dot, under 0.55 a dash, under 0.9 a plus, above that a bold plus. The colour is the canvas's CSS `color`.
- Cell size: `cell` (8px) on a stage screen, `cell-phone` (6px) on a phone, `cell-watermark` (4px) for a small still version.
- A mark sits in the middle of a cell. Snap every position with `Tacit.snap(value, cell)`; never draw between cells and never rotate or scale a mark.
- Density carries meaning: far ground is every second dot at 30%, a group's home ground is dots, the ground close to people is dashes, a person is a ring of pluses.
- No lines, curves, icons or illustrations next to these drawings.
