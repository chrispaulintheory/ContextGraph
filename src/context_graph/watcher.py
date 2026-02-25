"""File system watcher: detects changes and re-indexes automatically."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .db import Database
from .indexer import Indexer

# Directories to ignore
_IGNORE_DIRS = {".venv", "__pycache__", ".context_graph", "node_modules", ".git"}


def _should_ignore(path: str) -> bool:
    parts = Path(path).parts
    return any(p in _IGNORE_DIRS or p.startswith(".") for p in parts)


class _DebouncedHandler(FileSystemEventHandler):
    """Debounces rapid file changes before triggering re-index."""

    def __init__(self, indexer: Indexer, delay: float = 0.5):
        self.indexer = indexer
        self.delay = delay
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _schedule(self, path: str, action: str) -> None:
        with self._lock:
            if path in self._pending:
                self._pending[path].cancel()

            def _run():
                with self._lock:
                    self._pending.pop(path, None)
                if action == "delete":
                    self.indexer.remove_file(path)
                else:
                    try:
                        self.indexer.index_file(path)
                    except (OSError, ValueError):
                        pass

            timer = threading.Timer(self.delay, _run)
            self._pending[path] = timer
            timer.start()

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or not event.src_path.endswith(".py"):
            return
        rel = Path(event.src_path)
        if _should_ignore(str(rel)):
            return
        self._schedule(event.src_path, "index")

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or not event.src_path.endswith(".py"):
            return
        if _should_ignore(str(event.src_path)):
            return
        self._schedule(event.src_path, "index")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or not event.src_path.endswith(".py"):
            return
        if _should_ignore(str(event.src_path)):
            return
        self._schedule(event.src_path, "delete")

    def cancel_all(self) -> None:
        with self._lock:
            for timer in self._pending.values():
                timer.cancel()
            self._pending.clear()


class ProjectWatcher:
    """Watches a project directory for Python file changes."""

    def __init__(self, db: Database, project_root: str | Path):
        self.project_root = str(Path(project_root).resolve())
        self.indexer = Indexer(db, self.project_root)
        self._handler = _DebouncedHandler(self.indexer)
        self._observer = Observer()
        self._running = False

    def start(self) -> None:
        """Start watching for file changes."""
        if self._running:
            return
        self._observer.schedule(self._handler, self.project_root, recursive=True)
        self._observer.start()
        self._running = True

    def stop(self) -> None:
        """Stop watching."""
        if not self._running:
            return
        self._handler.cancel_all()
        self._observer.stop()
        self._observer.join(timeout=5)
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def index_now(self, force: bool = False) -> int:
        """Trigger a full project index immediately."""
        return self.indexer.index_project(force=force)
