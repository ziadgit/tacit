# Tacit

> A wearable wristband that listens 24/7, so you never lose the moment.

Built for the **Vexo Hackathon**.

## What it is

Tacit is an always-on, wrist-worn audio companion. It continuously listens to the world around you and turns conversations, ideas, and ambient context into something you can search, recall, and act on later.

## Features (planned)

- [ ] Always-on, low-power audio capture
- [ ] On-device voice activity detection (only process when someone is speaking)
- [ ] Transcription and speaker separation
- [ ] Summaries, highlights, and action items
- [ ] Searchable memory of your day
- [ ] Companion app for playback and review
- [ ] Privacy controls: mute, pause, delete, local-first storage

## How it works

```
[ Wristband mic ] -> [ VAD / buffering ] -> [ Sync to phone ] -> [ Transcribe + summarize ] -> [ App ]
```

_TODO: hardware, firmware, and backend details._

## Tech stack

- **Hardware:** TBD
- **Firmware:** TBD
- **Mobile / web app:** TBD
- **Backend / AI:** TBD

## Getting started

```bash
git clone <repo-url>
cd tacit
# setup instructions coming soon
```

## Privacy

A device that listens 24/7 has to earn trust. We're designing for:

- Clear on-device indicator when recording
- Easy one-tap mute
- Local-first processing where possible
- Full user control over retention and deletion

## Team

- _Add team members here_

## License

TBD
