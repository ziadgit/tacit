# tacit on a Raspberry Pi (an off-grid hub)

A Pi 4 or 5 runs `tacit bridge` for **one of the team's own bands** (16 or 74), and can run
`tacit serve` too, so phones on the Pi's Wi-Fi get the app locally. Without internet the bridge
buffers sound (`data/bridge/`, capped by `BRIDGE_BUFFER_MB`, 24 h at most) and syncs when the
internet comes back. Mute works offline. Exa, Vapi and Stripe need the internet.

These are instructions; nothing here is run by the build.

## 1. Install

64-bit Raspberry Pi OS (Bookworm), Python 3.11, BlueZ (already there).

```sh
sudo apt update && sudo apt install -y git bluez
sudo useradd --system --create-home --home-dir /opt/tacit --shell /usr/sbin/nologin tacit
sudo usermod -aG bluetooth tacit
sudo -u tacit -H bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u tacit -H git clone https://github.com/ziadgit/tacit /opt/tacit
cd /opt/tacit && sudo -u tacit -H scripts/bootstrap.sh
```

## 2. Configure

Pair the band in the app (`#/me` → "your band", on the phone), then put the lines it shows in
`/opt/tacit/.env`, with the band's number:

```sh
TACIT_BAND=74
TACIT_BRIDGE_TOKEN=...      # shown once in the app
TACIT_SERVER_URL=https://tacit-vexohacks.fly.dev
DEEPGRAM_API_KEY=...        # sound is sent to Deepgram while listening
```

`sudo chmod 600 /opt/tacit/.env && sudo chown tacit:tacit /opt/tacit/.env`. Check it:
`sudo -u tacit /opt/tacit/.venv/bin/tacit doctor`.

## 3. Bluetooth

The band is found by its exact name (`Vexo-HACK-74`); nothing else is ever connected. Close the
kit's dashboard and any laptop program connected to the band (one connection at a time), and
double-tap the band so it can be found for 60 s.

## 4. Run it as a service

```sh
sudo cp deploy/pi/tacit-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tacit-bridge
journalctl -u tacit-bridge -f            # logs: never transcripts or keys
```

`Restart=always` brings it back after a crash; it comes back **muted** if it was muted.

Optional: run the server on the Pi as well (`tacit serve --host 0.0.0.0`) and check
`http://<pi>:8000/healthz`: it adds `band_connected`, `listening`, `muted`, `buffer_mb` and
`last_sync` while the bridge runs.

## 5. Optional: an off-grid Wi-Fi network

With `hostapd` and `dnsmasq` the Pi can make its own Wi-Fi (for example `tacit-hub`), so phones
reach `http://10.0.0.1:8000/app/` with no internet. Follow the Raspberry Pi documentation for
"routed wireless access point"; keep a WPA2 password on it.
