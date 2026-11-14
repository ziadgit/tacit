# NetworkView

The network as people in loose groups: every person is a ring with a handwritten name, groups are a word and a denser patch of dots, and a skill passes when one person walks over to another.

- Markup: a `tc-ground tc-stage` element holding `<canvas class="tc-fx">`, empty `tc-labs` and `tc-names` layers, the wordmark, the listening pill and an empty `tc-chip`. Start it with `Tacit.field(canvas, stage, {K: 5, cell: 8})` and `Tacit.run`.
- The consumer provides people `{n, w}` (name, how much they have given from 0 to 1), links `[from, to, skill, author]`, three group words and which group each person belongs to. One real "A passed a skill to B" event is one link.
- Group words are: founders, creative professionals, engineers. A person who is two things sits between the two groups.
- There is no outline around a group and no line between people. The only thing that connects two people is the walk and the orange.
- It works with 3, 5 and 12 people; 12 reads most like a community.
- The same drawing with `still: true` and a 4px cell is the watermark.
