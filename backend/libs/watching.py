"""Filesystem watcher for the spell corpus.

Kept out of the CLI so the backend has no REPL dependency, and out of import scope so
importing any module has no side effects.
"""

from __future__ import annotations

import logging
import threading
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# The watcher starts only when a caller starts it, so importing this has no effect.
watch_thread = None


class ChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return
        logging.info(f"File {event.src_path} has been modified.")
        # Trigger rebuild logic here


def get_observer():
    """Create a fresh watchdog Observer.

    Observer instances are single-use: watchdog raises RuntimeError on a second
    start(), so one is built per run rather than at module import.
    """
    return Observer()


def stop_observer(observer):
    """Stop the watchdog thread, tolerating an observer that never started."""
    if observer is None:
        return
    try:
        observer.stop()
        observer.join(timeout=5)
    except Exception as e:
        logging.warning(f"Could not stop the file watcher cleanly: {e}")


def start_watching(path, observer):
    """Run the filesystem watcher until the process is interrupted.

    Exceptions are swallowed here so a failure in this background thread never tears
    down the REPL running on the main thread.
    """
    try:
        observer.schedule(ChangeHandler(), str(path), recursive=True)
        observer.start()

        # A plain sleep loop keeps the thread responsive to stop() without busy-waiting.
        while observer.is_alive():
            time.sleep(1)
    except Exception as e:
        logging.error(f"File watcher stopped unexpectedly: {e}")
    finally:
        stop_observer(observer)


def start_in_background(path, observer=None):
    """Start the watcher on a daemon thread and return ``(observer, thread)``."""
    global watch_thread

    observer = observer or get_observer()
    observer.start()
    watch_thread = threading.Thread(
        target=start_watching, args=(path, observer), daemon=True
    )
    watch_thread.start()
    return observer, watch_thread
