# PiFiles

PiFiles is a self-hosted file share and system dashboard for Raspberry Pi servers. Each server has its own independent storage.

## Setup

Pull this repository onto a Pi and run:

```sh
sudo bash ./setup.sh
```

The setup script installs and configures the services. The dashboard is available at `http://files.<hostname>.local/`; the file share can be opened from Windows Explorer using `\\<server-address>\PiFiles`.

The dashboard shows storage and system health, and lets devices on the local network view and start repository updates. Updates replace tracked repository changes, but shared files are stored separately. Keep the dashboard on a trusted local network and back up important files.
