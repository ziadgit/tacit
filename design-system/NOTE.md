# About this copy

This folder is a copy of the "Tacit Design System" (made in Claude), taken on 14 Nov 2026.

- `README.md`: the rules: words, colour, type, drawing, motion, do and do not, and the list of things still to confirm.
- `tokens.json`: colours, type roles, grid cells, radii, shadows.
- `components/bundle.css` and `components/bundle.js`: the shared classes (`tc-…`) and drawing code (`window.Tacit`).
- `components/<Name>/preview.html`: one live card per piece. Open any of them by double-click.

One change from the original: each `preview.html` got two lines in its head that load `../bundle.css` and `../bundle.js`
(the design-system viewer normally injects them).

The landing page in `landing/` follows this system with a few later choices by the team that are not written here yet:
a clean gradient with dots only where the community is, bolder rings for people, and no listening pill on the page.
