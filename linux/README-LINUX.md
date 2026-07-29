# KeirstinLink on Linux

Lightweight web-UI version of KeirstinLink for Linux (tested on Bazzite/Fedora, should work on any distro with Python 3).

## Install

```bash
bash ~/KeirstinLink/linux/install-keirstinlink-linux.sh
```

This clones the repo (if needed), installs Python dependencies, and creates data/sync folders.

## Launch

One-click:
```bash
bash ~/KeirstinLink/linux/keirstinlink-launch.sh
```

Or open the app menu and click **KeirstinLink**.

## What it does

1. Starts the KeirstinLink Python backend on `127.0.0.1:3710`
2. Opens your default browser to the web UI
3. If the backend is already running, it just opens the browser

## Auto-start backend on login

```bash
mkdir -p ~/.config/systemd/user
cp ~/KeirstinLink/linux/keirstinlink-backend.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now keirstinlink-backend
```

## Files

- `install-keirstinlink-linux.sh` — first-time install
- `keirstinlink-launch.sh` — one-click launcher
- `keirstinlink.desktop` — app menu entry
- `keirstinlink-backend.service` — systemd user service

## Notes

- The web UI is served from `src/` by the Python backend.
- The first time you run, open Settings and set Device name + Mode.
- Sync folder defaults to `~/KeirstinLinkSync`, master folder to `~/KeirstinLinkMaster`.
