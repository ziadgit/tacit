`tacit` is a network where people pick up skills from the people they talk to. A wristband listens while two people talk; when one explains how they do something, it is kept as a skill signed with that person's name, and the other person's agent can apply it. Two kinds of people open it: experts, whose skills and way of thinking are gathered, and learners. Every screen has to make sense to both within a few seconds.

The look: a soft lavender ground with grain and one warm glow, and drawings made only of plus signs, dashes and dots on a grid. People are the warm, handwritten part.

## words

- The product is `tacit`, always lower case.
- The unit is a **skill**. Never "move".
- Titles and headings are lower case. Sentences in running text keep their capitals.
- The tagline, taken for now: *agents have skills. people have taste. tacit is how it gets around.*
- A section heading is a plain phrase ("what maya never wrote down"), not a label.
- A person's own words are quoted exactly and set in handwriting.

## colour

Each colour means one thing. Do not borrow a colour for decoration.

| token | what it means |
| --- | --- |
| `ground-top`, `ground-mid`, `ground-deep` | the lavender ground, always as the 160-degree gradient with grain (`tc-ground`) |
| `glow-peach` | one warm glow per screen, behind the thing that matters |
| `glyph`, `cap` | cream: everything drawn or written on the ground |
| `listen` | blue: the band is listening. Nothing else uses this blue |
| `dot`, `dot-ring` | the dot of the i in the wordmark: small white dots around, blue-indigo in the centre. Nowhere else |
| `lit` | orange: a skill is passing right now. Off again when it has arrived |
| `pollen` | the name of the person who is explaining right now |
| `paper`, `ink` | cards and chips on the ground, and the text on them |
| `accent` | lavender on paper: the "after" example, the arrow in the chip |

Put small text on `ground-deep`, `ground-top` or on paper. Over `ground-mid` and over the peach glow, cream text needs to be 24px or larger and carry the `shade` text shadow, or sit on a card.

## type

| role | font | use it for |
| --- | --- | --- |
| wordmark | Geist Pixel, fine dots (`"ELSH" 50`) | the word `tacit`, nothing else. Write it `tac<span class="bi">i</span>t` inside `tc-word`, so the dot of the i gets its cluster of dots |
| titles | Instrument Serif | titles in lower case; the italic for the tagline, section phrases and group words |
| body | Instrument Sans | everything the product says; 20px or larger on a projector |
| people | Caveat | a person's name and their own words, nothing else |
| paths and time | IBM Plex Mono | a real file path, a time code |

Load the fonts from Google Fonts:

```html
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Instrument+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&family=Caveat:wght@600;700&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Geist+Pixel:ELSH@0..100&display=swap" rel="stylesheet">
```

## drawing

- Three marks: a dot, a dash, a plus. A bold plus marks a centre.
- One grid. A cell is `cell` (8px) on a stage, `cell-phone` (6px) on a phone, `cell-watermark` (4px) for a small still drawing. A mark sits in the middle of a cell; nothing is drawn between cells.
- Density carries meaning: far ground is every second dot at 30%, a group's home ground is dots, the ground close to people is dashes, a person is a ring of pluses.
- A person is a ring of pluses with a handwritten first name under it. The ring grows with how much the person has given.
- A group is a word in italic serif and a denser patch of dots. It has no outline.
- No lines between people, no icons, no illustrations, no photos next to these drawings.

Draw with `Tacit.pen`, `Tacit.ring` and `Tacit.field` from `components/bundle.js`; the shared classes (`tc-ground`, `tc-word`, `tc-pill`, `tc-chip`, `tc-card`, `tc-btn`) are in `components/bundle.css`.

## motion

- Drawings move one grid cell at a time, one tick every 110 ms: about nine frames a second.
- Blinking is on or off (`steps(1)`), never a fade.
- Only text pieces ease: the chip rises 8px in 0.35s, a name pulses once in 0.9s when its person receives a skill.
- A pass always goes the same way: the learner walks to the person who explains, both turn orange with a lit spot between them, the learner walks home still orange, the orange goes out.
- With reduced motion, show the settled frame.

## pieces

- **Wordmark**: `tacit` in the dot font with the tagline under it.
- **ListeningPill**: the only blue thing; top right of a screen.
- **PassChip**: who passed which skill to whom, with "from" when the skill was first someone else's.
- **PersonRing**: a person on the ground.
- **SkillCard**: one skill on a phone: what it is, see it work, what to do.
- **NetworkView**: people in loose groups; a skill passes when one walks over to another.

## do and do not

| do | do not |
| --- | --- |
| say "skill" | say "move" |
| lower-case titles, lower-case `tacit` | capitalised titles |
| section headings as plain italic serif phrases | small capital labels, numbered "01" markers |
| blue only for listening, orange only for a skill passing | blue or orange buttons, links, decoration |
| a person as a small ring with a handwritten name | people as flowers or petals, big overlapping circles, tiles, braided threads |
| a group as a word and denser dots | an outline or a big circle around a group |
| handwriting for a person's name and their own words | handwriting for headings, buttons, anything the product says |
| the dot font for the wordmark only | pixel type for text; a retro game look |
| a skill card that says what the skill is, shows it working, offers one action | a card that only names a skill |
| a phone drawn at real proportions, one screen, no scrolling | a tall scrolling phone |
| the dot of the i built from small dots: white around, blue-indigo in the centre | a solid round dot, a plus over the i, two dots over the i (reads as "ï"), a T in a square |

## to confirm

These are not decided. Do not present them as settled.

- **Orange for "a skill is passing".** It came with the network view and was never discussed by itself. It is under 3:1 against every ground colour, so it has to be looked at on the projector, most of all over the peach glow.
- **The dot of the i.** Its size (small, as here, or bigger) and the exact blue (`#3F3FFF`, a deeper indigo `#3326B8`, or a bluer `#2F4BFF`) are open.
- **The icon** (a blue dot with four pluses) was drawn for the earlier serif wordmark. Open: whether it stays, and in which blue.
- **The plus-sign flower.** Liked inside the phone player, turned down for the network. Open for the player and for a person's profile.
- **Small capital labels in the mono font.** They are on the liked skill card and were turned down on the profile. Until settled, use italic serif phrases.
- **The tagline** is taken "for now".
- **Secondary text on paper** (`accent-soft`) is 4:1, under the usual floor for 13px text.
- **Gesture tiles** (double tap, triple tap) and what each tap means.
- **The projector.** Nothing here has been seen on one. The two things most likely to wash out are the orange and cream names that sit on the peach glow.
