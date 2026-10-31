<p align="center"><img src="static/favicon.svg" alt="PiFiles favicon" width="64"></p>

# PiFiles 0.4.2

PiFiles turns a Raspberry Pi or Debian server into a local file share with a browser dashboard for storage and system health. Shared files are kept in their own directory, separate from the application repository.

## Features

- A Windows-compatible SMB share named `PiFiles` for storing and accessing files on the server.
- A live dashboard showing disk and share usage, CPU, memory, temperature, load average, and uptime.
- A monochrome, patterned storage chart that estimates file categories and shows free space.
- A dashboard action to pull the latest repository version and rerun setup.
- A configurable shared directory, independent from the repository so application updates leave shared files in place.

## Requirements

- Raspberry Pi OS or Debian.
- A network connection during installation so setup can install Python 3 and Samba.
- Clients on a trusted local network.

The SMB share allows guest access from `192.168.0.0/24` by default. If your LAN uses a different subnet, change `ALLOWED_SUBNET` in `setup.sh` before installing.

## Install

Clone the repository on the server and run setup:

```sh
git clone https://github.com/DirectedHunt42/PiFiles.git
cd PiFiles
sudo bash ./setup.sh
```

By default, shared files are stored in `/srv/pifiles`. To choose another directory, pass its path to setup:

```sh
sudo bash ./setup.sh /path/to/shared-files
```

Keep the shared directory outside the repository. If you use a mounted disk, mount it before setup and choose a directory inside that mount. Setup remembers the selected path for future updates.

## Connect

Setup prints the dashboard address and share path when it finishes. Open the dashboard from a browser on your local network, for example:

```text
http://192.168.0.42:8765/
```

Open the SMB share from Windows Explorer with `\\192.168.0.42\PiFiles`. On macOS or Linux, connect to `smb://192.168.0.42/PiFiles` using the file manager. Replace the example IP with the server's LAN address.

The share has no password and allows clients on its configured subnet to read and write files. The dashboard also has no login and listens on the server's network interfaces. Keep both on a trusted network and do not expose dashboard port `8765` to the public internet. Back up important files separately.

## Dashboard and updates

The dashboard refreshes system status automatically. Disk usage reports the filesystem containing the shared directory; share usage reports the size of files stored inside the share. The storage makeup chart estimates allocated file blocks on that filesystem, scanning in the background and refreshing every five minutes. Reserved blocks, filesystem metadata, and paths the dashboard cannot read appear as unclassified space. Temperature may show as unavailable if the system does not expose a supported sensor.

The **Update server** button pulls the latest repository revision and reruns setup while keeping the configured shared directory. It resets tracked repository changes before updating, so commit or back up any local edits to application files first. The shared files directory is separate and is not reset by this operation.
