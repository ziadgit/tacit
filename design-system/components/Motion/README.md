# Motion

Drawings move one grid cell at a time, one tick every 110 ms, which is about nine frames a second.

- Run a drawing with `Tacit.run(drawing, Tacit.TICK, element)`. It pauses off screen and shows a settled frame when the viewer asks for reduced motion.
- A position may glide in the numbers, but what is drawn is always snapped to the grid, so a ring steps from cell to cell.
- Blinking (the nine small pluses in the listening pill) uses `steps(1)`: on or off, no fading.
- Only pieces made of text may ease: the chip rises 8px in 0.35s; a name grows to 1.35 and back in 0.9s when that person receives a skill.
- A pass has a fixed order: the learner walks to the person who explains, both turn orange with a lit spot between them, the learner walks home still orange, then the orange goes out.
- No spinning, bouncing, parallax or smooth 60-frame movement inside drawings.
