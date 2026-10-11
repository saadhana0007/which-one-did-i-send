"""Folder watcher: debounce 1s, then hash + register. Scans once on startup."""
import os
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import engine
from db import BASE_DIR, ON_VERCEL

WATCH_DIR = Path(os.environ.get("WATCH_DIR", "/tmp/watched" if ON_VERCEL else BASE_DIR / "watched")).resolve()
DEBOUNCE = 1.0


def _ignored(p: Path) -> bool:
    n = p.name
    return n.startswith(("~$", ".")) or n.endswith((".tmp", ".crdownload", ".part"))


def process(path, retries=5):
    p = Path(path)
    if _ignored(p):
        return
    for i in range(retries):  # file may still be locked by the writer
        try:
            if p.is_file():
                engine.register_file(p)
            return
        except (PermissionError, OSError) as e:
            time.sleep(0.5 * (i + 1))
            last = e
    print(f"[watcher] gave up on {p}: {last}")


class Handler(FileSystemEventHandler):
    def __init__(self):
        self.timers = {}
        self.lock = threading.Lock()

    def schedule(self, path):
        with self.lock:
            t = self.timers.pop(path, None)
            if t:
                t.cancel()
            t = threading.Timer(DEBOUNCE, self._fire, args=(path,))
            t.daemon = True
            self.timers[path] = t
            t.start()

    def _fire(self, path):
        with self.lock:
            self.timers.pop(path, None)
        process(path)

    def on_created(self, e):
        if not e.is_directory:
            self.schedule(e.src_path)

    def on_modified(self, e):
        if not e.is_directory:
            self.schedule(e.src_path)

    def on_moved(self, e):  # rename: same hash -> only the path is refreshed
        if not e.is_directory:
            self.schedule(e.dest_path)


def scan_once():
    for root, _, files in os.walk(WATCH_DIR):
        for f in files:
            process(os.path.join(root, f))


def start():
    """Start the observer and an initial scan (in the background). Returns the observer."""
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    obs = Observer()
    obs.schedule(Handler(), str(WATCH_DIR), recursive=True)
    obs.start()
    threading.Thread(target=scan_once, daemon=True).start()
    print(f"[watcher] watching {WATCH_DIR}")
    return obs


if __name__ == "__main__":  # standalone mode
    import db
    db.init_db()
    o = start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        o.stop()
