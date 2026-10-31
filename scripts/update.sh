#!/usr/bin/env bash
set -Eeuo pipefail

readonly STATE_DIR="/var/lib/pifiles"
readonly STATUS_FILE="$STATE_DIR/update-status"
readonly LOG_FILE="/var/log/pifiles-update.log"
readonly LOCK_FILE="/run/lock/pifiles-update.lock"
readonly START_LOCK_FILE="/run/lock/pifiles-update-start.lock"

if [[ "$EUID" -ne 0 ]]; then
    echo "This updater must be run through the installed PiFiles service." >&2
    exit 1
fi

mkdir -p "$STATE_DIR"

set_status() {
    printf '%s\n' "$1" >"$STATUS_FILE"
    chmod 0644 "$STATUS_FILE"
}

if [[ "$#" -eq 0 ]]; then
    exec 8>"$START_LOCK_FILE"
    if ! flock -n 8; then
        echo "A PiFiles update is already starting." >&2
        exit 1
    fi
    current_status="$(cat "$STATUS_FILE" 2>/dev/null || true)"
    case "$current_status" in
        "Starting PiFiles update..."|"Updating PiFiles..."*)
            if ! flock -n "$LOCK_FILE" -c true; then
                echo "A PiFiles update is already running." >&2
                exit 1
            fi
            ;;
    esac

    : >"$LOG_FILE"
    chmod 0644 "$LOG_FILE"
    set_status "Starting PiFiles update..."
    if ! /usr/bin/systemd-run --quiet --collect --unit=pifiles-update \
        /usr/local/sbin/pifiles-update --run >>"$LOG_FILE" 2>&1; then
        set_status "Update failed to start. See the update output."
        exit 1
    fi
    exit 0
fi

if [[ "$#" -ne 1 || "$1" != "--run" ]]; then
    echo "Invalid updater invocation." >&2
    exit 2
fi

exec >>"$LOG_FILE" 2>&1
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "A PiFiles update is already running."
    exit 1
fi

trap 'result=$?; if [[ "$result" -ne 0 ]]; then set_status "Update failed (exit $result). See the update output."; fi' EXIT
set_status "Updating PiFiles..."

if [[ ! -r /etc/pifiles-update-repo || ! -r /etc/pifiles-data-dir ]]; then
    echo "PiFiles update configuration is missing." >&2
    exit 1
fi

repo_dir="$(realpath -e -- "$(cat /etc/pifiles-update-repo)")"
data_dir="$(realpath -m -- "$(cat /etc/pifiles-data-dir)")"
if [[ ! -d "$repo_dir/.git" || ! -f "$repo_dir/setup.sh" ]]; then
    echo "PiFiles repository was not found at $repo_dir." >&2
    exit 1
fi
if [[ "$data_dir" == "$repo_dir" || "$data_dir" == "$repo_dir/"* || "$repo_dir" == "$data_dir/"* ]]; then
    echo "Refusing to update: the shared files directory overlaps the repository." >&2
    exit 1
fi

repo_owner="$(stat -c '%U' "$repo_dir")"
run_as_repo_owner() {
    if [[ "$repo_owner" == "root" ]]; then
        "$@"
    else
        runuser -u "$repo_owner" -- "$@"
    fi
}

if [[ "$(realpath -e -- "$(run_as_repo_owner git -C "$repo_dir" rev-parse --show-toplevel)")" != "$repo_dir" ]]; then
    echo "Configured directory is not the root of the PiFiles Git checkout." >&2
    exit 1
fi

echo "Resetting tracked repository changes in $repo_dir"
run_as_repo_owner git -C "$repo_dir" reset --hard
echo "Pulling the latest repository version"
run_as_repo_owner git -C "$repo_dir" pull --ff-only

echo "Running PiFiles setup; the shared files directory remains $data_dir"
bash "$repo_dir/setup.sh" "$data_dir"

set_status "Update complete."
echo "PiFiles update complete."
trap - EXIT
