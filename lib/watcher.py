"""
Folder watcher for automatic MTR processing.

Uses the watchdog library to monitor an input directory for new PDF files
and triggers processing via a callback function.
"""

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Supported file extensions for auto-processing
WATCHED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff'}


class _NewFileHandler:
    """Watchdog event handler that fires a callback for new files."""

    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback

    def dispatch(self, event):
        """Called by watchdog for each filesystem event."""
        if event.is_directory:
            return
        if event.event_type not in ('created', 'moved'):
            return

        file_path = getattr(event, 'dest_path', None) or event.src_path
        ext = Path(file_path).suffix.lower()

        if ext in WATCHED_EXTENSIONS:
            logger.info("New file detected: %s", file_path)
            self.callback(file_path)


class FolderWatcher:
    """Monitors a folder for new MTR documents."""

    def __init__(self):
        self._observer = None
        self._watching = False
        self._folder: Optional[str] = None

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
        _inner = _NewFileHandler(on_new_file)
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
        logger.info("Stopped watching folder.")

    def is_watching(self) -> bool:
        """Return whether the watcher is currently active."""
        return self._watching

    @property
    def watched_folder(self) -> Optional[str]:
        """Return the currently watched folder path, or None."""
        return self._folder
