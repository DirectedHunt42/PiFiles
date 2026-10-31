# PiFiles

PiFiles configures a standalone, writable SMB share on Raspberry Pi OS or Debian. Run it independently on each Pi; each server stores files only on its own filesystem. It does not modify or integrate with other repositories or services.

## Install on each Pi

Pull this repository onto the Pi, then run:

```sh
sudo bash ./setup.sh
```

By default, files are stored in `/srv/pifiles`. To use another directory, pass an absolute path inside the filesystem you want to use:

```sh
sudo bash ./setup.sh /mnt/storage/pifiles
```

The script installs Samba, configures the `PiFiles` share, and enables the `smbd` service. It does not recursively change ownership of existing files; use a new, dedicated directory for the share. The share directory itself is owned by Samba's guest account so clients can add, edit, and delete files.

The share has no password and accepts clients only from `192.168.0.0/24` (plus localhost). If your LAN uses a different subnet, update `ALLOWED_SUBNET` near the top of `setup.sh` before running it. Do not expose SMB to the public internet.

## Connect from Windows

In File Explorer's address bar, enter the Pi's address, for example:

```text
\\192.168.0.41\PiFiles
\\192.168.0.42\PiFiles
```

Each address is an independent share. To assign a drive letter, use **This PC → Map network drive** and enter one of those paths. If Windows prompts for credentials, choose the Guest account with a blank password. Some Windows editions block unauthenticated SMB guest access by default; their local security policy may need to allow insecure guest logons. Enabling guest access reduces security, so only do that on a trusted private network.

## Storage behavior

The share has no configured quota or reserved size: it uses the free space of the filesystem containing its shared directory and can grow as files are added. It does not combine the two Pis' capacity, mirror files, or provide backup. Windows may show the capacity/free space of the whole underlying filesystem, not just the share. To use a separate disk, mount it and pass a directory inside that mounted filesystem to `setup.sh`.
