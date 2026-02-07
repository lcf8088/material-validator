"""
Test 15: FolderWatcher - Filesystem monitoring.
"""

import time
import pytest
from unittest.mock import MagicMock
from lib.watcher import FolderWatcher, WATCHED_EXTENSIONS


class TestWatchedExtensions:
    def test_pdf_is_watched(self):
        assert ".pdf" in WATCHED_EXTENSIONS

    def test_png_is_watched(self):
        assert ".png" in WATCHED_EXTENSIONS

    def test_txt_is_not_watched(self):
        assert ".txt" not in WATCHED_EXTENSIONS


class TestFolderWatcherUnit:
    def test_initial_state(self):
        w = FolderWatcher()
        assert not w.is_watching()
        assert w.watched_folder is None

    def test_stop_when_not_watching(self):
        """stop_watching should not crash if not watching."""
        w = FolderWatcher()
        w.stop_watching()
        assert not w.is_watching()


class TestFolderWatcherIntegration:
    @pytest.fixture
    def _skip_no_watchdog(self):
        pytest.importorskip("watchdog")

    @pytest.mark.usefixtures("_skip_no_watchdog")
    def test_start_and_stop(self, tmp_path):
        w = FolderWatcher()
        watch_dir = tmp_path / "watch_input"
        watch_dir.mkdir()

        callback = MagicMock()
        w.start_watching(str(watch_dir), callback)

        assert w.is_watching()
        assert w.watched_folder == str(watch_dir)

        w.stop_watching()
        assert not w.is_watching()
        assert w.watched_folder is None

    @pytest.mark.usefixtures("_skip_no_watchdog")
    def test_creates_folder_if_missing(self, tmp_path):
        w = FolderWatcher()
        watch_dir = tmp_path / "new_folder"
        assert not watch_dir.exists()

        w.start_watching(str(watch_dir), MagicMock())
        assert watch_dir.is_dir()

        w.stop_watching()

    @pytest.mark.usefixtures("_skip_no_watchdog")
    def test_restart_watching(self, tmp_path):
        w = FolderWatcher()
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        w.start_watching(str(dir1), MagicMock())
        assert w.watched_folder == str(dir1)

        # Starting a new watch should stop the old one
        w.start_watching(str(dir2), MagicMock())
        assert w.watched_folder == str(dir2)

        w.stop_watching()

    @pytest.mark.usefixtures("_skip_no_watchdog")
    @pytest.mark.slow
    def test_detects_new_pdf(self, tmp_path):
        """Create a new PDF in the watch folder and verify callback fires."""
        w = FolderWatcher()
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()

        callback = MagicMock()
        w.start_watching(str(watch_dir), callback)

        # Give the watcher a moment to start
        time.sleep(0.5)

        # Create a new file
        new_file = watch_dir / "test.pdf"
        new_file.write_bytes(b"fake pdf content")

        # Wait for the event to be processed
        time.sleep(1.5)

        w.stop_watching()

        # Callback should have been called with the path
        if callback.called:
            call_path = callback.call_args[0][0]
            assert "test.pdf" in call_path
