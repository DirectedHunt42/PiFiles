#!/usr/bin/env bash
set -Eeuo pipefail

readonly SHARE_NAME="PiFiles"
readonly SMB_CONFIG="/etc/samba/smb.conf"
readonly SHARE_CONFIG="/etc/samba/pifiles-share.conf"
readonly ALLOWED_SUBNET="192.168.0.0/24"
readonly APP_DIR="/opt/pifiles"
readonly SERVICE_NAME="pifiles-dashboard"
readonly UPDATE_COMMAND="/usr/local/sbin/pifiles-update"

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
if [[ ! -f "$repo_dir/app.py" || ! -f "$repo_dir/scripts/update.sh" || ! -d "$repo_dir/static" ]]; then
    printf 'Run setup from the complete File-server repository checkout.\n' >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y avahi-daemon avahi-utils nginx python3 samba

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
install -o root -g root -m 0644 "$repo_dir/static/app.js" "$APP_DIR/app.js"
install -o root -g root -m 0644 "$repo_dir/static/light.css" "$APP_DIR/light.css"
install -o root -g root -m 0644 "$repo_dir/static/dark.css" "$APP_DIR/dark.css"
install -o root -g root -m 0755 "$repo_dir/scripts/update.sh" "$UPDATE_COMMAND"

token_created=0
if [[ ! -s /etc/pifiles-update-token ]]; then
    umask 027
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))' >/etc/pifiles-update-token
    token_created=1
fi
chown root:pifiles /etc/pifiles-update-token
chmod 0640 /etc/pifiles-update-token
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
Environment=PIFILES_UPDATE_TOKEN_FILE=/etc/pifiles-update-token
Environment=PIFILES_UPDATE_COMMAND=$UPDATE_COMMAND
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

host_name="$(hostname -s)"
if [[ ! "$host_name" =~ ^[A-Za-z0-9-]+$ ]]; then
    printf 'The system hostname cannot be used to configure the files dashboard address: %s\n' "$host_name" >&2
    exit 1
fi
dashboard_host="files.${host_name,,}.local"
cat >/etc/nginx/sites-available/pifiles <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $dashboard_host;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF
ln -sfn /etc/nginx/sites-available/pifiles /etc/nginx/sites-enabled/pifiles
nginx -t

cat >/usr/local/sbin/pifiles-publish-mdns <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
host_name="$(hostname -s | tr '[:upper:]' '[:lower:]')"
ip_address="$(hostname -I | awk '{print $1}')"
if [[ -z "$host_name" || -z "$ip_address" ]]; then
    echo "Could not determine the Pi hostname or LAN address for mDNS publishing." >&2
    exit 1
fi
exec /usr/bin/avahi-publish-address "files.${host_name}.local" "$ip_address"
EOF
chmod 0755 /usr/local/sbin/pifiles-publish-mdns

cat >/etc/systemd/system/pifiles-mdns.service <<'EOF'
[Unit]
Description=Publish the PiFiles dashboard mDNS hostname
After=avahi-daemon.service network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/pifiles-publish-mdns
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now avahi-daemon nginx "$SERVICE_NAME" pifiles-mdns.service
systemctl restart "$SERVICE_NAME"
systemctl reload nginx

printf '\nShare is ready: \\\\%s\\%s\n' "$(hostname -I | awk '{print $1}')" "$SHARE_NAME"
printf 'Shared directory: %s\n' "$data_dir"
printf 'Allowed client subnet: %s\n' "$ALLOWED_SUBNET"
printf 'Storage uses the free space on the filesystem containing the shared directory.\n'
printf 'Dashboard: http://%s/\n' "$dashboard_host"
if [[ "$token_created" -eq 1 ]]; then
    printf 'Dashboard update token: %s\n' "$(cat /etc/pifiles-update-token)"
fi
