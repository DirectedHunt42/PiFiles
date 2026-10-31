#!/usr/bin/env bash
set -Eeuo pipefail

readonly SHARE_NAME="PiFiles"
readonly SMB_CONFIG="/etc/samba/smb.conf"
readonly SHARE_CONFIG="/etc/samba/pifiles-share.conf"
readonly ALLOWED_SUBNET="192.168.0.0/24"

if [[ "${EUID}" -ne 0 ]]; then
    printf 'Run this script with sudo, for example: sudo bash ./setup.sh\n' >&2
    exit 1
fi

if [[ "$#" -gt 1 ]]; then
    printf 'Usage: sudo %s [shared-directory]\n' "$0" >&2
    exit 2
fi

if [[ ! -r /etc/os-release ]]; then
    printf 'Cannot identify the operating system; expected Raspberry Pi OS or Debian.\n' >&2
    exit 1
fi

. /etc/os-release
if [[ "${ID:-}" != "raspbian" && "${ID:-}" != "debian" && " ${ID_LIKE:-} " != *" debian "* ]]; then
    printf 'This setup script supports Raspberry Pi OS and Debian.\n' >&2
    exit 1
fi

data_dir="${1:-/srv/pifiles}"
if [[ "$data_dir" != /* ]]; then
    data_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$data_dir"
fi
data_dir="$(realpath -m -- "$data_dir")"

if [[ "$data_dir" == "/" || "$data_dir" == "/srv" || "$data_dir" == "/mnt" || "$data_dir" == "/media" ]]; then
    printf 'Choose a dedicated directory for the share, not a filesystem root or mount-point directory.\n' >&2
    exit 2
fi
if [[ "$data_dir" == *'"'* || "$data_dir" == *$'\n'* ]]; then
    printf 'The shared-directory path cannot contain a double quote or newline.\n' >&2
    exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y samba

if [[ ! -f "$SMB_CONFIG" ]]; then
    printf 'Samba did not create its configuration file at %s.\n' "$SMB_CONFIG" >&2
    exit 1
fi

if ! testparm -s "$SMB_CONFIG" >/dev/null; then
    printf 'The existing Samba configuration is invalid; fix it before installing this share.\n' >&2
    exit 1
fi

mkdir -p -- "$data_dir"
if command -v mountpoint >/dev/null 2>&1 && mountpoint -q -- "$data_dir"; then
    printf 'The shared directory is itself a mount point. Choose a directory inside the mounted filesystem.\n' >&2
    exit 2
fi
chown nobody:nogroup "$data_dir"
chmod 2775 "$data_dir"

config_tmp="$(mktemp "${SHARE_CONFIG}.XXXXXX")"
main_tmp=""
share_backup=""
share_existed=0
cleanup() {
    rm -f -- "$config_tmp"
    if [[ -n "$main_tmp" ]]; then
        rm -f -- "$main_tmp"
    fi
    if [[ -n "$share_backup" ]]; then
        rm -f -- "$share_backup"
    fi
}
trap cleanup EXIT

if [[ -e "$SHARE_CONFIG" ]]; then
    share_backup="$(mktemp "${SHARE_CONFIG}.backup.XXXXXX")"
    cp -p -- "$SHARE_CONFIG" "$share_backup"
    share_existed=1
fi

cat >"$config_tmp" <<EOF
[$SHARE_NAME]
   path = "$data_dir"
   browseable = yes
   read only = no
   guest ok = yes
   guest only = yes
   force user = nobody
   force group = nogroup
   create mask = 0664
   directory mask = 2775
   hosts allow = $ALLOWED_SUBNET 127.
EOF

install -o root -g root -m 0644 "$config_tmp" "$SHARE_CONFIG"

include_line="include = $SHARE_CONFIG"
if ! grep -Fqx -- "$include_line" "$SMB_CONFIG"; then
    main_tmp="$(mktemp "${SMB_CONFIG}.XXXXXX")"
    cp -p -- "$SMB_CONFIG" "$main_tmp"
    printf '\n%s\n' "$include_line" >>"$SMB_CONFIG"
fi

if ! testparm -s "$SMB_CONFIG" >/dev/null; then
    if [[ -n "$main_tmp" ]]; then
        cp -p -- "$main_tmp" "$SMB_CONFIG"
    fi
    if [[ "$share_existed" -eq 1 ]]; then
        cp -p -- "$share_backup" "$SHARE_CONFIG"
    else
        rm -f -- "$SHARE_CONFIG"
    fi
    printf 'The resulting Samba configuration is invalid; the previous main configuration was restored.\n' >&2
    exit 1
fi

systemctl enable --now smbd
systemctl reload smbd

printf '\nShare is ready: \\\\%s\\%s\n' "$(hostname -I | awk '{print $1}')" "$SHARE_NAME"
printf 'Shared directory: %s\n' "$data_dir"
printf 'Allowed client subnet: %s\n' "$ALLOWED_SUBNET"
printf 'Storage uses the free space on the filesystem containing the shared directory.\n'
