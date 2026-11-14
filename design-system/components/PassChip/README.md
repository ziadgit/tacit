# PassChip

A paper chip that names who passed which skill to whom; it is what makes the moving rings readable without explanation.

- Markup: `<div class="tc-chip"><b>Maya</b><i>→</i><b>You</b><em>Open with the number</em></div>`. Names in handwriting, the skill title in the body font.
- When the skill was first someone else's, add `<small>from Maya</small>` at the end, so the author stays visible however far the skill travels.
- On a stage it sits bottom left, 20px from the edge, and rises in each time a new pass starts.
- One chip at a time. Do not stack a history of chips.
