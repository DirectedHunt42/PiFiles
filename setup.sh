#!/usr/bin/env bash
set -Eeuo pipefail

readonly SHARE_NAME="PiFiles"
readonly SMB_CONFIG="/etc/samba/smb.conf"
readonly SHARE_CONFIG="/etc/samba/pifiles-share.conf"
readonly ALLOWED_SUBNET="192.168.0.0/24"
readonly APP_DIR="/opt/pifiles"
readonly SERVICE_NAME="pifiles-dashboard"
readonly UPDATE_COMMAND="/usr/local/sbin/pifiles-update"
readonly DASHBOARD_PORT="8765"
readonly LEGACY_NGINX_SITE_LINK="/etc/nginx/sites-enabled/zzzzzz-pifiles"

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

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
saved_data_dir=""
if [[ -r /etc/pifiles-data-dir ]]; then
    saved_data_dir="$(cat /etc/pifiles-data-dir)"
fi
data_dir="${1:-${saved_data_dir:-/srv/pifiles}}"
if [[ "$data_dir" != /* ]]; then
    data_dir="$repo_dir/$data_dir"
fi
data_dir="$(realpath -m -- "$data_dir")"
repo_dir="$(realpath -m -- "$repo_dir")"

if [[ "$data_dir" == "/" || "$data_dir" == "/srv" || "$data_dir" == "/mnt" || "$data_dir" == "/media" ]]; then
    printf 'Choose a dedicated directory for the share, not a filesystem root or mount-point directory.\n' >&2
    exit 2
fi
if [[ "$data_dir" == *'"'* || "$data_dir" == *$'\n'* ]]; then
    printf 'The shared-directory path cannot contain a double quote or newline.\n' >&2
    exit 2
fi
if [[ "$data_dir" == "$repo_dir" || "$data_dir" == "$repo_dir/"* || "$repo_dir" == "$data_dir/"* ]]; then
    printf 'Keep the shared directory separate from the repository so updates cannot affect stored files.\n' >&2
    exit 2
fi
if [[ ! -f "$repo_dir/app.py" || ! -f "$repo_dir/LICENSE.txt" || ! -f "$repo_dir/scripts/update.sh" || ! -d "$repo_dir/static" ]]; then
    printf 'Run setup from the complete PiFiles repository checkout.\n' >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 samba

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
printf '%s\n' "$data_dir" >/etc/pifiles-data-dir
chmod 0644 /etc/pifiles-data-dir

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

if ! id pifiles >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin pifiles
fi
install -d -o root -g root -m 0755 "$APP_DIR"
install -o root -g root -m 0644 "$repo_dir/app.py" "$APP_DIR/app.py"
install -o root -g root -m 0644 "$repo_dir/index.html" "$APP_DIR/index.html"
install -o root -g root -m 0644 "$repo_dir/LICENSE.txt" "$APP_DIR/LICENSE.txt"
install -o root -g root -m 0644 "$repo_dir/static/app.js" "$APP_DIR/app.js"
install -o root -g root -m 0644 "$repo_dir/static/light.css" "$APP_DIR/light.css"
install -o root -g root -m 0644 "$repo_dir/static/dark.css" "$APP_DIR/dark.css"
install -d -o root -g root -m 0755 "$APP_DIR/static"
install -o root -g root -m 0644 "$repo_dir/static/favicon.svg" "$APP_DIR/static/favicon.svg"
install -d -o root -g root -m 0755 "$APP_DIR/static/icons"
for icon in server storage folder processor memory temperature clock refresh; do
    install -o root -g root -m 0644 "$repo_dir/static/icons/$icon.svg" "$APP_DIR/static/icons/$icon.svg"
done
install -o root -g root -m 0755 "$repo_dir/scripts/update.sh" "$UPDATE_COMMAND"

rm -f /etc/pifiles-update-token
printf '%s\n' "$repo_dir" >/etc/pifiles-update-repo
chmod 0644 /etc/pifiles-update-repo

cat >/etc/sudoers.d/pifiles-dashboard <<'EOF'
pifiles ALL=(root) NOPASSWD: /usr/local/sbin/pifiles-update ""
EOF
chmod 0440 /etc/sudoers.d/pifiles-dashboard
visudo -cf /etc/sudoers.d/pifiles-dashboard

cat >/etc/systemd/system/pifiles-dashboard.service <<EOF
[Unit]
Description=PiFiles system dashboard
After=network.target

[Service]
Type=simple
User=pifiles
Group=pifiles
WorkingDirectory=$APP_DIR
Environment="PIFILES_DATA_DIR=$data_dir"
Environment=PIFILES_UPDATE_COMMAND=$UPDATE_COMMAND
Environment=PIFILES_HOST=0.0.0.0
Environment=PIFILES_PORT=$DASHBOARD_PORT
ExecStart=/usr/bin/python3 $APP_DIR/app.py
Restart=on-failure
RestartSec=3
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadOnlyPaths="$data_dir"

[Install]
WantedBy=multi-user.target
EOF

legacy_nginx_config=0
if [[ -e "$LEGACY_NGINX_SITE_LINK" || -L "$LEGACY_NGINX_SITE_LINK" || -e /etc/nginx/sites-enabled/pifiles || -e /etc/nginx/sites-available/pifiles ]]; then
    rm -f -- "$LEGACY_NGINX_SITE_LINK" /etc/nginx/sites-enabled/pifiles /etc/nginx/sites-available/pifiles
    legacy_nginx_config=1
fi
if [[ "$legacy_nginx_config" -eq 1 ]] && systemctl is-active --quiet nginx; then
    nginx -t
    systemctl reload nginx
fi

systemctl disable --now pifiles-mdns.service 2>/dev/null || true
rm -f -- /etc/systemd/system/pifiles-mdns.service /usr/local/sbin/pifiles-publish-mdns
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

ip_address="$(hostname -I | awk '{print $1}')"
if [[ -z "$ip_address" ]]; then
    printf 'Could not determine the Pi LAN address for the dashboard URL.\n' >&2
    exit 1
fi
printf '\nShare is ready: \\\\%s\\%s\n' "$ip_address" "$SHARE_NAME"
printf 'Shared directory: %s\n' "$data_dir"
printf 'Allowed client subnet: %s\n' "$ALLOWED_SUBNET"
printf 'Storage uses the free space on the filesystem containing the shared directory.\n'
printf 'Dashboard: http://%s:%s/\n' "$ip_address" "$DASHBOARD_PORT"
