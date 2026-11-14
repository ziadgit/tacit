# screens

Static pictures of the app's screens in plain HTML and CSS, one folder per screen. They show the layout and
the words; they have no data, no voice and no navigation. The real app (`pwa/` in `SPEC.md`) can copy the
markup and the styles from here.

Each screen was drawn first in Subframe (project "Tacit", canvas "Tacit app") and follows
`design-system/README.md`. People on these screens are invented examples: Maya is "me" ("You"), and Leo,
Kai, Noor and Sam are the people she met. Every line of advice, skill and time is example text.

## feed

`feed/index.html`, `feed/feed.css`. To open it, serve the repository folder and go to `/screens/feed/`:

    python3 -m http.server 8000 --bind 127.0.0.1

What the feed is:

- **Lines, not cards.** Who, what they did, and the thing itself in one bold line. Cream text on the
  lavender ground, a dashed rule between two lines, almost no boxes, so it can be scanned quickly.
- **It starts with advice.** Advice is what one person told another to do or try, with the reason
  ("because"). Advice about a product carries a chip with the brand.
- **Kinds of line drawn here:** advice about a product, advice in general, "someone used your skill",
  a new skill from someone you follow (their own words in handwriting, "send to my agent"), and
  "you and Kai connected" with what you talked about.
- **It can be asked out loud:** "show me the advice I heard today", "what fits what I'm working on?".
- **Tabs:** everything / advice / skills / people. Only "everything" is drawn.
- **Shell, the same on every app screen:** feed · network · profile and the button "+ connect"; the blue
  "Listening" pill top right. On a phone the four sit in a bar at the bottom.
- **Wide screens** get a side column: "people you met today" and "your network recommends". On a phone the
  people move to a row at the top and "recommends" is hidden.

Type on this screen: the serif is used for the page title only; everything else the product says is in
Instrument Sans; handwriting is for a person's name and their own words.

Not done: the other three tabs, any data, the voice commands, links between screens.

The two dot portraits and the brand logo are files in `feed/img/` (copied from the Subframe project). If one
cannot be loaded, the page shows a dotted ring with the initial, or the chip without a logo.
