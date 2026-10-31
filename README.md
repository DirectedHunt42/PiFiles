# PiFiles

PiFiles is a standalone SMB file share and lightweight system dashboard for Raspberry Pi OS or Debian. Install it separately on each Pi; storage is not pooled or replicated, and the other repositories are left untouched.

## Install on each Pi

Pull this repository onto the Pi, then run:

```sh
sudo bash ./setup.sh
```

By default, files are stored in `/srv/pifiles`. To choose another directory on a mounted filesystem, pass it on the first install:

```sh
sudo bash ./setup.sh /mnt/storage/pifiles
```

The chosen directory is saved in `/etc/pifiles-data-dir` and reused by later updates. It must remain outside the repository. Setup installs Samba, Nginx, Avahi, and a small Python dashboard service. It does not recursively change ownership of files already in the share; the directory itself is owned by Samba's guest account.

## Dashboard

Setup publishes an mDNS hostname based on the Pi's existing hostname:

```text
http://files.<pi-hostname>.local/
```

For the Pi whose hostname is `skychopper`, this is `http://files.skychopper.local/`. The dashboard reports filesystem usage/free space, total bytes in the file share, CPU, memory, temperature when available, and uptime. It follows the browser/device light or dark preference using separate stylesheets.

The first setup prints an update token. Enter it in the dashboard to view update output or run an update. The updater resets tracked Git changes, pulls the current branch's latest commits, and reruns setup. Untracked repository files are preserved. **Keep shared files in the configured data directory**: setup refuses a data directory overlapping the checkout, and the updater checks again before resetting. Updates do not run `git clean` or delete share contents.

The update token is stored in `/etc/pifiles-update-token`; to retrieve it later, run `sudo cat /etc/pifiles-update-token` on the Pi. Keep it private: it authorizes a repository update and setup run. The dashboard uses HTTP, so only use the token on a trusted LAN; do not expose or port-forward the dashboard to the internet.

## Connect to the share from Windows

In File Explorer's address bar, enter the Pi's address, for example:

```text
\\192.168.0.41\PiFiles
\\192.168.0.42\PiFiles
```

Each address is an independent share. To assign a drive letter, use **This PC → Map network drive** and enter one of those paths. The SMB share has no password and accepts clients only from `192.168.0.0/24` (plus localhost). If your LAN uses another subnet, update `ALLOWED_SUBNET` near the top of `setup.sh` before running it. Windows editions may block unauthenticated SMB guest access by default. Do not expose SMB to the public internet.

The share has no configured quota or reserved size: it uses free space on the filesystem containing the data directory. It does not combine the two Pis' capacity, mirror files, or provide backup. Windows may show the underlying filesystem's full capacity rather than only the share.

## Tests

Run the dashboard API tests with:

```sh
python3 -m unittest discover -s tests
```
