# PiFiles 0.3.0

PiFiles is a self-hosted file share and system dashboard for Raspberry Pi servers. Each server has its own independent storage.

## Setup

Pull this repository onto a Pi and run:

```sh
sudo bash ./setup.sh
```

After setup, open the printed dashboard URL from any computer on the same local network. It uses the Pi's LAN address and dedicated port 8765, for example `http://192.168.0.42:8765/`. This avoids local DNS setup and keeps the dashboard separate from other websites hosted on the Pi.

The file share can be opened from Windows Explorer using `\\<server-address>\PiFiles`.

The dashboard shows storage and system health, and lets devices on the local network view and start repository updates. Updates replace tracked repository changes, but shared files are stored separately. Keep the dashboard on a trusted local network and back up important files.
