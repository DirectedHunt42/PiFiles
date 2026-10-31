#!/usr/bin/env python3
import json
import logging
import os
import platform
import shutil
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
