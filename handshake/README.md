# Handshake

How two people connect in Tacit: they shake hands, and both wristbands feel it.

## What a handshake means

Two people who each wear a band shake hands. Both bands feel the same short motion at the same moment, and Tacit takes that as "these two have met and both agreed to connect". It is mutual and visible: nobody can do it alone, and nobody can do it to you without your hand in theirs.

## How it is recognised

In a handshake the two hands are joined, so both wrists make the same up-and-down motion together.

1. Each band sends its motion 50 times a second.
2. For each band we look at the last 1.2 seconds and ask: is it shaking? That means a few quick swings, strong enough.
3. If both are shaking, we lay the two traces over each other and measure how closely they match, allowing a small shift in time.
4. If they match closely, it is a handshake. After one handshake, the next one counts only three seconds later.

One person shaking a hand alone does not pass step 3, and neither do two people who happen to move at the same time but not together.

The signal is the size of the acceleration, so it does not matter how each band sits on the wrist.

## The numbers

These are starting values, not measured on a set of real handshakes yet. The page has sliders for the two that matter most.

| Setting | Value | Meaning |
|---|---|---|
| `windowMs` | 1200 | How much of the recent past is compared |
| `stepMs` | 20 | Both traces are put on this common time grid |
| `minEnergy` | 0.2 g | How strong the shake must be (slider) |
| `minSwings` – `maxSwings` | 4 – 16 | At least two full up-and-downs, and not a buzz |
| `minMatch` | 0.6 | How closely the two traces must agree, 0 to 1 (slider) |
| `maxLagMs` | 160 | How far apart in time the two traces may be |
| `cooldownMs` | 3000 | Pause before the next handshake counts |

## Try it

You need the kit cloned in the repository folder (`scripts/bootstrap.sh` does that) and the team's two bands. Their numbers live in one place, `TEAM_BANDS` in `src/tacit/config.py`; they are typed on the page and never written in this folder.

In the repository folder:

    python3 -m http.server 8000 --bind 127.0.0.1

Then open `http://localhost:8000/handshake/` in Google Chrome or Edge on a laptop. It does not work in Safari, Firefox, on a phone, or in a browser pane embedded in another app: those cannot show the Bluetooth list.

1. Close anything else that is connected to either band (the kit's dashboard, another program, the other laptop). A band takes one connection at a time.
2. Type your band's number, press Connect, double-tap the band (it blinks blue) and pick it in the list.
3. Do the same for your teammate's band.
4. Shake hands. The circle turns green and both bands blink white together.

Without bands: open `http://localhost:8000/handshake/?demo=1` and use the four "Pretend" buttons.

## What has been checked

- **The logic, on made-up motion:** `node --test handshake/detector.test.mjs` runs five cases and all pass. A handshake is recognised once; one person shaking alone, two people shaking at different rhythms, and both people just moving around are not; a long handshake is not counted twice.
- **Real bands:** tried on 14 November 2026 with the team's two bands connected to one laptop. Handshakes were recognised. No counts were recorded, and nothing has been measured yet for things that should not count (clapping in time, walking side by side).

## Limits

- **Both bands must be connected to the same computer.** One Chrome tab holds both Bluetooth links. With a band on each laptop, each side would have to send its last second of motion to a shared place to be compared; that is not built.
- **It only detects.** Nothing in the product reacts yet. The natural next step is that the two people's profiles connect.
- **A handshake can also set off the band's own tap and double-tap events.** Anything that uses taps should ignore them for about a second around a handshake. Not wired in.
- **Two people doing the same rhythmic thing together** (clapping in time, carrying something) could look like a handshake. Not measured.

## Files

| File | What it is |
|---|---|
| `handshake-detector.js` | The logic only: no page, no Bluetooth, no dependencies. About a hundred lines, easy to port to Python for the band bridge |
| `handshake.js`, `index.html` | The test page: connects two bands, draws both traces, shows the match |
| `detector.test.mjs` | The five checks on made-up motion |

The page never turns the microphone on, so the band's light is free to blink, and no keys are involved.
