# PersonRing

A person is a small ring of plus signs with a bold plus in the middle and their name in handwriting underneath.

- Draw it with `Tacit.ring(put, x, y, radius, cell)`. The radius grows with how much the person has given: between 1.9 and 3.1 cells.
- The name is HTML, not canvas: class `tc-nm`, centred under the ring, first name only.
- Keep about one cell of empty ground around the ring so it reads as a ring.
- While a skill passes, collect both rings and the cells between them into a list and draw them with `Tacit.drawHot` in `lit`.
- Do not draw people as flowers, petals, photos, initials in circles or tiles. Do not put an outline around a group of people: a group is a word in italic serif plus a denser patch of dots.
