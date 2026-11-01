<p align="center"><img src="static/favicon.svg" alt="PiFiles favicon" width="64"></p>

# PiFiles 0.4.7

PiFiles adds a network file share and a small server status dashboard to a Raspberry Pi or Debian machine. It is intended to sit alongside services you already run, including an existing website. It does not replace your web server or serve your website's content.

## What it adds

- An authenticated SMB share named `PiFiles`, which you can open or map as a network drive from Windows, macOS, or Linux.
- A browser dashboard for share and disk usage, CPU, memory, temperature, load, and uptime.
- A storage chart that estimates how disk space is being used.
- A dashboard button for updating PiFiles from its Git repository.
- A separate data directory for shared files, so application updates do not overwrite them.

## How it fits beside a web server

PiFiles runs two separate services:

- Its dashboard is served by a small Python service on port `8765` (HTTP). It serves its own page and status API; it does not need Nginx, Apache, or another web server.
- Samba serves the `PiFiles` network share over SMB. This is separate from the dashboard and is what Windows connects to when mapping a drive.

Your existing website can keep using its normal HTTP and HTTPS ports, usually `80` and `443`. You can open the PiFiles dashboard directly at `http://SERVER-IP:8765/`. If you want a cleaner URL, you can configure your existing reverse proxy to send a dedicated hostname to the dashboard. PiFiles expects to run at the root of that hostname, so proxying it under a URL path such as `/pifiles/` is not supported by default.

The setup script does not install a web server or take over ports `80` and `443`. When upgrading an older PiFiles installation, it removes the legacy Nginx site entries that were specifically named for PiFiles.

## Requirements and network access

- Raspberry Pi OS or Debian.
- Internet access during installation so setup can install Python 3 and Samba.
- Clients on a trusted local network.

The SMB share is limited to `192.168.0.0/24` by default. If your LAN uses another subnet, change `ALLOWED_SUBNET` near the top of `setup.sh` before installing. The dashboard has no login and listens on the server's network interfaces. Keep it on a trusted network, and do not expose port `8765` to the public internet.

## Install

Clone the repository on the server and run setup:

```sh
git clone https://github.com/DirectedHunt42/PiFiles.git
cd PiFiles
sudo bash ./setup.sh
```

Shared files are stored in `/srv/pifiles` by default. To choose another directory, pass its path to setup:

```sh
sudo bash ./setup.sh /path/to/shared-files
```

Keep the shared directory outside the repository. If you use a mounted disk, mount it before setup and choose a directory inside that mount. Setup remembers the selected path for future updates.

Setup installs and configures Samba and a `pifiles-dashboard` system service. It prints the dashboard address and share path when it finishes.

## Connect

Open the dashboard from a browser on your local network. For example:

```text
http://192.168.0.42:8765/
```

In Windows Explorer, open `\\192.168.0.42\PiFiles` or use **Map network drive** and enter that path. When Windows asks for credentials, use the SMB username and password below. On macOS or Linux, connect to `smb://192.168.0.42/PiFiles` in the file manager. Replace the example IP with the server's LAN address.

The default SMB credentials are:

- Username: `pifiles`
- Password: `PiFiles123`

Setup saves the configured username and password in `/etc/pifiles-smb-user` and `/etc/pifiles-smb-password`. They are readable by root and the dashboard service so the dashboard can show them. Anyone who can reach the dashboard can view the credentials; keep dashboard access limited to a trusted network. To read the password on the server, run `sudo cat /etc/pifiles-smb-password`.

To choose custom SMB credentials during setup, provide `PIFILES_SMB_USER` and `PIFILES_SMB_PASSWORD` in the environment. For example, in Bash:

```sh
export PIFILES_SMB_USER=files
read -rsp 'SMB password: ' PIFILES_SMB_PASSWORD; echo
export PIFILES_SMB_PASSWORD
sudo --preserve-env=PIFILES_SMB_USER,PIFILES_SMB_PASSWORD bash ./setup.sh
unset PIFILES_SMB_USER PIFILES_SMB_PASSWORD
```

The configured credentials are kept for later setup runs. If you change them, run setup again so Samba applies the new values.

## Storage and dashboard

Shared files are kept in their own directory, separate from the application files installed under `/opt/pifiles`. Samba writes files in the share as the `nobody` system account. Keep a separate backup of important files.

The dashboard refreshes system status automatically. Disk usage describes the filesystem containing the shared directory; share usage measures files stored inside the share. The storage makeup chart estimates allocated file blocks on that filesystem, scans in the background, and refreshes every five minutes. Reserved blocks, filesystem metadata, and paths the dashboard cannot read appear as unclassified space. Temperature may be unavailable if the system does not expose a supported sensor.

## Updates

The **Update server** button pulls the latest repository revision and reruns setup while keeping the configured shared directory and SMB credentials. The updater resets tracked changes in the repository before updating. Commit or back up local changes to application files first; shared files are stored separately and are not reset.
