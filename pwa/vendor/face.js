/* Copied from landing/landing.js (`face()`, the dot-portrait renderer; do not edit here, edit the
   source). Only the wrapper is new: it takes fit/reduce/run from the design system's
   window.Tacit (vendor/bundle.js) and exposes window.TacitFace.draw(canvas, rows). */
(function () {
  'use strict';
  var T = window.Tacit, fit = T.fit, reduce = T.reduce, run = T.run, TICK = T.TICK;
  function face(cv, rows) {
    var n = 0;
    function draw() {
      var S = fit(cv), W = S.W, H = S.H, ctx = S.ctx, cols = rows[0].length, cs = getComputedStyle(cv);
      function tone(name, fallback) { return (cs.getPropertyValue(name) || '').trim() || fallback; }
      var hair = tone('--ink', '#231E3D'), skin = tone('--pollen', '#FFE2A8'), cloth = tone('--glyph', '#FFFDF6'), lip = '#C0607A';
      var s = Math.max(4, Math.floor(Math.min(W / (cols + 1), H / (rows.length + 0.5)))), rad = s * 0.44;
      var x0 = Math.round((W - cols * s) / 2 + s / 2), y0 = Math.round(H - rows.length * s + s / 2);   /* the shoulders sit on the bottom edge */
      var blink = !reduce && (n % 44 === 42 || n % 44 === 43);
      ctx.clearRect(0, 0, W, H);
      for (var r = 0; r < rows.length; r++) for (var c = 0; c < cols; c++) {
        var ch = rows[r].charAt(c);
        if (ch === ' ' || ch === '') continue;
        ctx.fillStyle = ch === '#' ? hair : ch === '+' ? cloth : ch === '-' ? lip : (ch === 'o' && !blink) ? hair : skin;
        ctx.beginPath(); ctx.arc(x0 + c * s, y0 + r * s, rad, 0, 6.2832); ctx.fill();
      }
    }
    draw();
    return { warm: 1, tick: function () { n++; var k = n % 44; if (k === 42 || k === 0) draw(); }, resize: draw };
  }
  window.TacitFace = { draw: function (cv, rows) { return run(face(cv, rows), TICK, cv); }, face: face };
})();
