# voice

A test page for opening the app's screens by voice from the wristband: "Vexo, open the feed".
It connects one band over Web Bluetooth, sends the band's microphone to Deepgram for live text,
listens for commands in that text, and switches the screen it shows. Two files, no build step,
nothing to install: `index.html` and `voice-commands.js`.

## Run it

    scripts/bootstrap.sh                               # once: puts ./vexo-open-kit next to this folder
    python3 -m http.server 8000 --bind 127.0.0.1       # in the repository folder

Open `http://localhost:8000/voice/?band=NN` in Chrome or Edge, with your own band in place of NN (your
`TACIT_BAND`, one of `TEAM_BANDS`). No band number is written in the code. Close every other tab or
program that holds the band first: it takes one Bluetooth connection.

1. **Connect band NN**, double-tap the band, pick it in the browser's list.
2. Type the team's Deepgram key into the key field. It stays in that page's memory only (never in the
   address, in storage or in a file), and goes to Deepgram in the WebSocket's protocol field.
3. Tell the people near you, then **Turn microphone on**. The band's light goes solid blue; it hears
   everyone nearby and the sound goes to Deepgram (`mip_opt_out=true`). The page shows a line that says
   so for as long as the microphone is on.

With no band and no key, the box "Type a command" and the buttons under it run the same logic.

## Commands

| Say | What happens |
|---|---|
| "Vexo, open the feed" | the feed: the real page in `screens/feed/` |
| "Vexo, open my profile" | the profile (a picture of the design) |
| "Vexo, open the network" | the network (a picture of the design) |
| "Vexo, connect" | the connect screen (a picture of the design) |
| "Vexo, go back" | the screen before |
| "Vexo, stop listening" | the microphone goes off, nothing more is sent |
| "What did Ziad recommend me today?" | Ziad's page (a picture of the design); no wake word needed |

- **Loose wording works:** "show me the feed", "go to feed".
- **Two ways to give a command.** The wake word, at any time while the microphone is on. Or double-tap
  the band and say the command within 6 seconds, with no wake word. With the microphone off, a
  double-tap turns it on first.
- **Mishearings of "Vexo" are expected** and matched: "Vex oh", "Vexa", "Texaco", "Mexico", and any word
  one letter away from "vexo". Deepgram is also told the words (`keyterm=Vexo`, `keyterm=Ziad`). Add a
  new mishearing to `WAKE_WORDS` in `voice-commands.js` when the log shows one.
- **It is keyword matching, not understanding.** A command is decided in the page from the words after
  the wake word, at once, with no model call. The question about Ziad works because it has his name
  plus a word like "recommend"; an arbitrary question does not.
- **The band cannot answer:** no speaker, no vibration, and no LED while the microphone is on. The
  answer is the screen, plus a short sound from the laptop.

The **Test log** at the bottom of the page counts what was understood, by which way, and how long
after the last word the screen changed; it also notes a "Vexo" with no command after it and a command
with no "Vexo" in front. "Copy the log" puts it on the clipboard.

## Not done

- Only the feed is a real page. Profile, network, connect and Ziad's page are pictures in `shots/`
  (exported from the Subframe project) until those screens exist in `screens/`.
- This page is separate from the mute path in `SPEC.md` §13.2. "Vexo, stop listening" only turns this
  page's microphone off; it is not the safety-critical mute and does not replace it.
- No automated test. The matching was checked by hand on typed sentences, and the team tried it by
  voice on a band at the event; recognition counts in the hall were not recorded.
