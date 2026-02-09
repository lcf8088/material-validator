"""
Folder watcher for automatic MTR processing.

Uses the watchdog library to monitor an input directory for new PDF files
and triggers processing via a callback function.
"""

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Set

logger = logging.getLogger(__name__)

# Supported file extensions for auto-processing
WATCHED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff'}

# Delay before processing a new file (seconds) — lets copies finish
_STABILITY_DELAY = 1.5
_STABILITY_CHECK_INTERVAL = 0.5


def _wait_for_stable(file_path: str, timeout: float = _STABILITY_DELAY) -> bool:
    """Wait until a file's size is stable (copy finished).

    Returns True if the file stabilised, False if it disappeared or timed out.
    """
    prev_size = -1
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            size = os.path.getsize(file_path)
        except OSError:
            return False
        if size == prev_size and size > 0:
            return True
        prev_size = size
        time.sleep(_STABILITY_CHECK_INTERVAL)
    # Final check
    try:
        return os.path.getsize(file_path) == prev_size and prev_size > 0
    except OSError:
        return False


class _NewFileHandler:
    """Watchdog event handler that fires a callback for new files."""

    def __init__(self, callback: Callable[[str], None], watcher: 'FolderWatcher'):
        self.callback = callback
        self.watcher = watcher

    def dispatch(self, event):
        """Called by watchdog for each filesystem event."""
        if event.is_directory:
            return
        if event.event_type not in ('created', 'moved'):
            return

        file_path = getattr(event, 'dest_path', None) or event.src_path
        ext = Path(file_path).suffix.lower()

        if ext not in WATCHED_EXTENSIONS:
            return

        if self.watcher.is_processed(file_path):
            return

        logger.info("New file detected: %s — waiting for stability", file_path)

        def _delayed_callback():
            if _wait_for_stable(file_path):
                if not self.watcher.is_processed(file_path):
                    logger.info("File stable, firing callback: %s", file_path)
                    self.callback(file_path)
            else:
                logger.warning("File not stable or disappeared: %s", file_path)

        threading.Thread(target=_delayed_callback, daemon=True).start()


class FolderWatcher:
    """Monitors a folder for new MTR documents."""

    def __init__(self):
        self._observer = None
        self._watching = False
        self._folder: Optional[str] = None
        self._processed: Set[str] = set()
        self._lock = threading.Lock()

    def start_watching(self, folder: str, on_new_file: Callable[[str], None]):
        """
        Start watching a folder for new files.

        Args:
            folder: Directory path to watch.
            on_new_file: Callback invoked with the new file path.
        """
        if self._watching:
            self.stop_watching()

        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        # Create a proper watchdog handler by subclassing
        handler = FileSystemEventHandler()
        _inner = _NewFileHandler(on_new_file, self)
        handler.on_created = _inner.dispatch
        handler.on_moved = _inner.dispatch

        folder_path = Path(folder)
        if not folder_path.is_dir():
            folder_path.mkdir(parents=True, exist_ok=True)

        self._observer = Observer()
        self._observer.schedule(handler, str(folder_path), recursive=False)
        self._observer.start()
        self._watching = True
        self._folder = str(folder_path)

        logger.info("Started watching folder: %s", folder_path)

    def stop_watching(self):
        """Stop the folder watcher."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self._watching = False
        self._folder = None
        self.reset_processed()
        logger.info("Stopped watching folder.")

    def is_watching(self) -> bool:
        """Return whether the watcher is currently active."""
        return self._watching

    @property
    def watched_folder(self) -> Optional[str]:
        """Return the currently watched folder path, or None."""
        return self._folder

    # ---- Processed-file tracking ----

    def mark_processed(self, file_path: str):
        """Add a file to the processed set so it won't be re-triggered."""
        with self._lock:
            self._processed.add(os.path.normpath(file_path))

    def is_processed(self, file_path: str) -> bool:
        """Check whether a file has already been processed."""
        with self._lock:
            return os.path.normpath(file_path) in self._processed

    def reset_processed(self):
        """Clear the processed-file set."""
        with self._lock:
            self._processed.clear()
