#!/usr/bin/env python3
import json
import logging
import os
import platform
import shutil
import stat
import subprocess
import threading
import time
from collections import deque
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PIFILES_DATA_DIR", "/srv/pifiles")).resolve()
UPDATE_COMMAND = os.environ.get("PIFILES_UPDATE_COMMAND", "/usr/local/sbin/pifiles-update")
UPDATE_STATUS = Path("/var/lib/pifiles/update-status")
UPDATE_LOG = Path("/var/log/pifiles-update.log")
HOST = os.environ.get("PIFILES_HOST", "127.0.0.1")
PORT = int(os.environ.get("PIFILES_PORT", "8765"))

_previous_cpu = None
_snapshot = None
_snapshot_at = 0.0
_snapshot_lock = threading.Lock()
_share_snapshot = None
_share_snapshot_at = 0.0
_share_snapshot_lock = threading.Lock()
_storage_snapshot = None
_storage_snapshot_at = 0.0
_storage_scan_in_progress = False
_storage_snapshot_lock = threading.Lock()

STORAGE_SCAN_INTERVAL = 300
STORAGE_CATEGORIES = (
    ("system", "System files"),
    ("other_repos", "Other repos"),
    ("this_repo", "This repo"),
    ("unrelated", "Unrelated files"),
    ("stored", "Stored files"),
    ("unclassified", "Unclassified"),
    ("empty", "Empty space"),
)
SYSTEM_DIRECTORIES = {"bin", "boot", "etc", "lib", "lib32", "lib64", "opt", "sbin", "usr", "var"}
CATEGORY_PRIORITY = {"unrelated": 0, "system": 1, "other_repos": 2, "this_repo": 3, "stored": 4}
CURRENT_REPO_ROOTS = {ROOT}
try:
    configured_repo = Path("/etc/pifiles-update-repo").read_text(encoding="utf-8").strip()
    if configured_repo:
        configured_repo = Path(configured_repo).resolve()
        if configured_repo.is_dir():
            CURRENT_REPO_ROOTS.add(configured_repo)
except OSError:
    pass


def read_cpu_percent():
    global _previous_cpu
    try:
        fields = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()
        values = [int(value) for value in fields[1:]]
    except (OSError, ValueError, IndexError):
        return None

    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    previous = _previous_cpu
    _previous_cpu = (total, idle)
    if previous is None or total <= previous[0]:
        return 0
    elapsed = total - previous[0]
    return round(max(0, min(100, (elapsed - (idle - previous[1])) * 100 / elapsed)))


def read_memory():
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
        total = values["MemTotal"]
        available = values["MemAvailable"]
        used = total - available
        return {
            "used": used,
            "total": total,
            "percent": round(used * 100 / total) if total else 0,
        }
    except (OSError, ValueError, KeyError, IndexError):
        return None


def read_temperature():
    readings = []
    for sensor in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            readings.append(int(sensor.read_text(encoding="ascii").strip()) / 1000)
        except (OSError, ValueError):
            continue
    if readings:
        return round(max(readings), 1)
    try:
        output = subprocess.run(
            ["/usr/bin/vcgencmd", "measure_temp"],
            capture_output=True,
            text=True,
            timeout=1,
            check=True,
        ).stdout.strip()
        return round(float(output.removeprefix("temp=").removesuffix("'C")), 1)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def read_share_size():
    try:
        used = 0
        pending = [DATA_DIR]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        used += entry.stat(follow_symlinks=False).st_size
        return used, None
    except OSError as error:
        return None, str(error)


def get_share_size():
    global _share_snapshot, _share_snapshot_at
    with _share_snapshot_lock:
        now = time.monotonic()
        if _share_snapshot is None or now - _share_snapshot_at >= 30:
            _share_snapshot = read_share_size()
            _share_snapshot_at = now
        return _share_snapshot


def path_is_within(path, directory):
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def mount_path_from_mountinfo(data_device):
    """Find the mounted filesystem root containing DATA_DIR and nested mounts to skip."""
    mount_entries = []
    nested_mounts = set()
    try:
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError:
        mountinfo = ""

    for line in mountinfo.splitlines():
        fields = line.split(" - ", 1)[0].split()
        if len(fields) < 5 or fields[2] != f"{os.major(data_device)}:{os.minor(data_device)}":
            continue
        mount_text = fields[4]
        for escaped, character in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
            mount_text = mount_text.replace(escaped, character)
        mount_path = Path(mount_text)
        mount_entries.append(mount_path)

    containing_mounts = [path for path in mount_entries if path_is_within(DATA_DIR, path)]
    if containing_mounts:
        filesystem_root = max(containing_mounts, key=lambda path: len(path.parts))
        nested_mounts = {
            path for path in mount_entries
            if path != filesystem_root and path_is_within(path, filesystem_root)
        }
        return filesystem_root, nested_mounts

    # Fallback for systems without mountinfo: find the first ancestor on another device.
    filesystem_root = DATA_DIR
    while filesystem_root.parent != filesystem_root:
        try:
            if filesystem_root.parent.stat().st_dev != data_device:
                break
        except OSError:
            break
        filesystem_root = filesystem_root.parent
    return filesystem_root, nested_mounts


def storage_category(path, in_repository):
    if path_is_within(path, DATA_DIR):
        return "stored"
    if any(path_is_within(path, repository) for repository in CURRENT_REPO_ROOTS):
        return "this_repo"
    if in_repository:
        return "other_repos"
    parts = path.parts
    if len(parts) > 1 and parts[0] == "/" and parts[1] in SYSTEM_DIRECTORIES:
        return "system"
    return "unrelated"


def scan_storage_usage():
    """Estimate allocated bytes per category without following symlinks or crossing mounts."""
    data_device = DATA_DIR.stat().st_dev
    filesystem_root, nested_mounts = mount_path_from_mountinfo(data_device)
    category_bytes = {category: 0 for category, _ in STORAGE_CATEGORIES if category != "empty"}
    seen_inodes = {}
    skipped_entries = 0
    pending = [(filesystem_root, False, filesystem_root.stat())]

    def record_usage(file_stat, category):
        allocated = file_stat.st_blocks * 512 if hasattr(file_stat, "st_blocks") else file_stat.st_size
        if stat.S_ISDIR(file_stat.st_mode) or file_stat.st_nlink <= 1:
            category_bytes[category] += allocated
            return
        inode = (file_stat.st_dev, file_stat.st_ino)
        previous = seen_inodes.get(inode)
        if previous is None:
            seen_inodes[inode] = (category, allocated)
            category_bytes[category] += allocated
        elif CATEGORY_PRIORITY[category] > CATEGORY_PRIORITY[previous[0]]:
            old_category, old_allocated = previous
            category_bytes[old_category] -= old_allocated
            category_bytes[category] += old_allocated
            seen_inodes[inode] = (category, old_allocated)

    while pending:
        directory, parent_is_repository, directory_stat = pending.pop()
        if directory_stat.st_dev != data_device or directory in nested_mounts:
            continue
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError:
            skipped_entries += 1
            continue

        is_repository = parent_is_repository
        for entry in entries:
            if entry.name != ".git":
                continue
            try:
                is_repository = is_repository or entry.is_dir(follow_symlinks=False) or entry.is_file(follow_symlinks=False)
            except OSError:
                skipped_entries += 1
            break
        record_usage(directory_stat, storage_category(directory, is_repository))

        for entry in entries:
            entry_path = Path(entry.path)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError:
                skipped_entries += 1
                continue
            if stat.S_ISDIR(entry_stat.st_mode):
                if entry_stat.st_dev == data_device and entry_path not in nested_mounts:
                    pending.append((entry_path, is_repository, entry_stat))
                continue
            record_usage(entry_stat, storage_category(entry_path, is_repository))

    return category_bytes, skipped_entries


def run_storage_scan():
    global _storage_snapshot, _storage_snapshot_at, _storage_scan_in_progress
    try:
        category_bytes, skipped_entries = scan_storage_usage()
        disk = shutil.disk_usage(DATA_DIR)
        measured = sum(category_bytes.values())
        if measured > disk.used and measured:
            scale = disk.used / measured
            category_bytes = {key: int(value * scale) for key, value in category_bytes.items()}
        accounted = sum(category_bytes.values())
        category_bytes["unclassified"] += max(0, disk.used - accounted)
        snapshot = {
            "status": "ready",
            "partial": skipped_entries > 0,
            "categories": category_bytes,
            "disk": {"used": disk.used, "total": disk.total, "available": disk.free},
            "scanned_at": int(time.time()),
        }
    except Exception:
        logging.exception("Could not scan filesystem storage usage")
        snapshot = {"status": "error", "partial": True, "categories": None, "disk": None}

    with _storage_snapshot_lock:
        _storage_snapshot = snapshot
        _storage_snapshot_at = time.monotonic()
        _storage_scan_in_progress = False


def get_storage_breakdown():
    global _storage_snapshot, _storage_snapshot_at, _storage_scan_in_progress
    start_scan = False
    with _storage_snapshot_lock:
        if not _storage_scan_in_progress and (
            _storage_snapshot is None or time.monotonic() - _storage_snapshot_at >= STORAGE_SCAN_INTERVAL
        ):
            _storage_scan_in_progress = True
            if _storage_snapshot is None:
                _storage_snapshot = {"status": "scanning", "partial": False, "categories": None, "disk": None}
            start_scan = True
        snapshot = dict(_storage_snapshot)

    if start_scan:
        threading.Thread(target=run_storage_scan, daemon=True, name="storage-breakdown-scan").start()
    return snapshot


def build_stats():
    disk = shutil.disk_usage(DATA_DIR)
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text(encoding="ascii").split()[0])
        uptime = str(timedelta(seconds=int(uptime_seconds)))
    except (OSError, ValueError, IndexError):
        uptime = None
    try:
        load_average = [round(value, 2) for value in os.getloadavg()]
    except (AttributeError, OSError):
        load_average = None
    share_used, share_error = get_share_size()
    return {
        "hostname": platform.node(),
        "uptime": uptime,
        "load_average": load_average,
        "cpu_percent": read_cpu_percent(),
        "memory": read_memory(),
        "temperature_c": read_temperature(),
        "disk": {
            "used": disk.used,
            "total": disk.total,
            "available": disk.free,
            "percent": round(disk.used * 100 / disk.total) if disk.total else 0,
        },
        "storage_breakdown": get_storage_breakdown(),
        "share": {"path": str(DATA_DIR), "used": share_used, "error": share_error},
        "sampled_at": int(time.time()),
    }


def get_stats():
    global _snapshot, _snapshot_at
    with _snapshot_lock:
        now = time.monotonic()
        if _snapshot is None or now - _snapshot_at >= 4:
            _snapshot = build_stats()
            _snapshot_at = now
        return _snapshot


def tail_update_log(limit=100):
    try:
        with UPDATE_LOG.open("r", encoding="utf-8", errors="replace") as log_file:
            lines = list(deque(log_file, maxlen=limit))
        return "".join(lines)[-20000:]
    except FileNotFoundError:
        return "Update log is empty."
    except OSError:
        logging.exception("Could not read updater log")
        return "Update output is temporarily unavailable."


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "PiFiles"

    def log_message(self, format_string, *args):
        logging.info("%s - %s", self.client_address[0], format_string % args)

    def send_bytes(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_bytes(status, "application/json; charset=utf-8", body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/stats":
            try:
                self.send_json(200, get_stats())
            except OSError:
                logging.exception("Could not read dashboard system stats")
                self.send_json(503, {"error": "System statistics are temporarily unavailable."})
            return
        if path == "/api/update":
            try:
                status = UPDATE_STATUS.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                status = "Ready to update."
            except OSError:
                logging.exception("Could not read updater status")
                self.send_json(503, {"error": "Update status is temporarily unavailable."})
                return
            self.send_json(200, {"status": status, "output": tail_update_log()})
            return

        static_files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/light.css": ("light.css", "text/css; charset=utf-8"),
            "/dark.css": ("dark.css", "text/css; charset=utf-8"),
            "/license.txt": ("LICENSE.txt", "text/plain; charset=utf-8"),
            "/favicon.svg": ("static/favicon.svg", "image/svg+xml"),
            "/icons/server.svg": ("static/icons/server.svg", "image/svg+xml"),
            "/icons/storage.svg": ("static/icons/storage.svg", "image/svg+xml"),
            "/icons/folder.svg": ("static/icons/folder.svg", "image/svg+xml"),
            "/icons/processor.svg": ("static/icons/processor.svg", "image/svg+xml"),
            "/icons/memory.svg": ("static/icons/memory.svg", "image/svg+xml"),
            "/icons/temperature.svg": ("static/icons/temperature.svg", "image/svg+xml"),
            "/icons/clock.svg": ("static/icons/clock.svg", "image/svg+xml"),
            "/icons/refresh.svg": ("static/icons/refresh.svg", "image/svg+xml"),
        }
        asset = static_files.get(path)
        if asset is None:
            self.send_json(404, {"error": "Not found."})
            return
        filename, content_type = asset
        try:
            body = (ROOT / filename).read_bytes()
        except OSError:
            logging.exception("Could not read dashboard asset %s", filename)
            self.send_json(500, {"error": "Dashboard asset is unavailable."})
            return
        self.send_bytes(200, content_type, body)

    def do_POST(self):
        if urlparse(self.path).path != "/api/update":
            self.send_json(404, {"error": "Not found."})
            return

        try:
            subprocess.run(
                ["sudo", "-n", UPDATE_COMMAND],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            self.send_json(504, {"error": "The updater did not respond in time."})
            return
        except subprocess.CalledProcessError as error:
            message = error.stderr.strip() or error.stdout.strip() or "The updater could not start."
            self.send_json(409, {"error": message[-500:]})
            return
        except OSError:
            logging.exception("Could not start the repository updater")
            self.send_json(503, {"error": "The updater could not be started."})
            return
        self.send_json(202, {"status": "Update started."})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    logging.info("PiFiles dashboard listening on %s:%s", HOST, PORT)
    server.serve_forever()
