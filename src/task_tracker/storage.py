"""
JSON persistence for the Task Tracker application.

This is the only module that touches the disk. It implements the
`Storage` protocol the service depends on (`load` and `save`) and owns
every promise the README makes about the tasks file:

- the file is created on the first write, never on a read;
- writes are atomic: the file is either the old version or the new one;
- a file it cannot understand is reported and never overwritten;
- old schema versions are migrated, newer ones are refused.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from task_tracker.errors import (
    CorruptStorageError,
    InvalidTaskDataError,
    StorageAccessError,
    UnsupportedSchemaError,
)
from task_tracker.models import Task

SCHEMA_VERSION = 1
"""Version of the file format this program reads and writes."""

DEFAULT_FILENAME = "tasks.json"
ENV_VAR = "TASK_CLI_FILE"


def resolve_path() -> Path:
    """
    Decide which file to use: `$TASK_CLI_FILE` if set, else ./tasks.json.

    Why an environment variable: the contract says "current directory",
    which is right for users but painful for tests and scripts. The
    variable lets them point the program elsewhere without a new flag.

    Why a function and not a constant: the current directory and the
    environment are read at call time, not at import time, so a test
    that changes either one sees the change.
    """
    override = os.environ.get(ENV_VAR)
    return Path(override) if override else Path.cwd() / DEFAULT_FILENAME


def empty_state() -> dict:
    """
    Return the data of a store with no tasks.

    Why a function: it returns a fresh dict every time. A shared
    module-level dict would be mutated by the first caller and leak
    tasks into the next one.
    """
    return {"version": SCHEMA_VERSION, "next_id": 1, "tasks": []}


class JsonTaskStorage:
    """
    Load and save the task data as a JSON file.

    Satisfies the `Storage` protocol defined in `service.py` without
    inheriting from it: the service only needs `load()` and `save()`.
    """

    def __init__(self, path: Path) -> None:
        """
        Args:
            path: File to read and write. Its parent directory must exist.

        Why the path is injected: the class does not decide where data
        lives. The CLI passes `resolve_path()`; tests pass a temp file.
        """
        self.path = Path(path)

    # ------------------------------------------------------------------
    # Storage protocol
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """
        Read, migrate and validate the file.

        Why a missing file is not an error: it is the normal state before
        the first `add`. Returning an empty store (without creating the
        file) keeps read commands side-effect free, as the contract says.

        Why validate everything here: a bad file is caught once, at the
        boundary, with a message that names the file. The service can
        then trust the data it receives.

        Returns:
            A dict with `version`, `next_id` and `tasks`.

        Raises:
            CorruptStorageError: Invalid JSON or invalid structure.
            UnsupportedSchemaError: Written by a newer version.
            StorageAccessError: The OS refused to read the file.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return empty_state()
        except UnicodeDecodeError as e:
            raise self._corrupt("not valid UTF-8") from e
        except OSError as e:
            raise StorageAccessError(
                f"cannot read {self.path.name}: {e.strerror or e}"
            ) from e

        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            raise self._corrupt("invalid JSON") from e

        data = self._migrate(raw)
        self._validate(data)
        return data

    def save(self, data: dict) -> None:
        """
        Write the data atomically.

        How: write to a temporary file in the same directory, force it to
        disk with `fsync`, then `os.replace` it over the real file.

        Why: writing straight into tasks.json truncates it first. If the
        process dies halfway (Ctrl+C, power cut, full disk), the user is
        left with half a file and loses every task. `os.replace` swaps
        the file in one step, so readers see the old or the new version,
        never a mix.

        Why the same directory: `os.replace` is only atomic inside one
        filesystem. /tmp is often a different one.

        Why `fsync`: without it the OS may still hold the new bytes in
        memory when the rename happens; a crash then leaves an empty file.

        Raises:
            StorageAccessError: The OS refused to write.
        """
        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
            )
        except OSError as e:
            raise StorageAccessError(
                f"cannot write {self.path.name}: {e.strerror or e}"
            ) from e

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self.path)
        except BaseException as e:
            # Why BaseException: Ctrl+C raises KeyboardInterrupt, which is
            # not an Exception. The temp file must be removed either way.
            Path(tmp_name).unlink(missing_ok=True)
            if isinstance(e, OSError):
                raise StorageAccessError(
                    f"cannot write {self.path.name}: {e.strerror or e}"
                ) from e
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _migrate(self, raw: object) -> dict:
        """
        Bring older file formats up to the current schema, in memory.

        Why it exists: the format will change one day. Each version gets
        one step here, so old files keep working instead of breaking.
        The migrated data is written back only on the next save, so a
        read never modifies the file.

        Known formats:
            version 0: a bare list of tasks (the beginner version of this
                       project, without `version` or `next_id`).
            version 1: the current format.

        Raises:
            UnsupportedSchemaError: The version is newer than this program.
            CorruptStorageError: The version field is not a valid integer.
        """
        if isinstance(raw, list):
            ids = [t.get("id") for t in raw if isinstance(t, dict)]
            numeric = [i for i in ids if type(i) is int]
            raw = {
                "version": 1,
                "next_id": max(numeric, default=0) + 1,
                "tasks": raw,
            }

        if not isinstance(raw, dict):
            raise self._corrupt("expected a JSON object")

        version = raw.get("version")
        if type(version) is not int or version < 1:
            raise self._corrupt("missing or invalid 'version'")
        if version > SCHEMA_VERSION:
            raise UnsupportedSchemaError(
                f"{self.path.name} uses schema version {version}; "
                f"this program supports up to {SCHEMA_VERSION}"
            )
        return raw

    def _validate(self, data: dict) -> None:
        """
        Check that the data is internally consistent.

        Why each rule:
        - every task must parse: otherwise the service crashes later with
          a message that does not mention the file;
        - IDs must be unique: `update 3` must mean exactly one task;
        - `next_id` must be above every ID: otherwise the next `add`
          would reuse an existing ID.

        Why `type(x) is int` and not `isinstance`: `True` is an int in
        Python, and `"next_id": true` must be rejected.

        Raises:
            CorruptStorageError: Any rule is broken.
        """
        next_id = data.get("next_id")
        tasks = data.get("tasks")

        if type(next_id) is not int or next_id < 1:
            raise self._corrupt("missing or invalid 'next_id'")
        if not isinstance(tasks, list):
            raise self._corrupt("missing or invalid 'tasks'")

        seen: set[int] = set()
        for raw in tasks:
            if not isinstance(raw, dict):
                raise self._corrupt("every task must be a JSON object")
            try:
                task = Task.from_dict(raw)
            except InvalidTaskDataError as e:
                raise self._corrupt(f"invalid task {raw.get('id')!r}") from e
            if type(task.id) is not int or task.id < 1:
                raise self._corrupt(f"invalid task id {task.id!r}")
            if task.id in seen:
                raise self._corrupt(f"duplicate task id {task.id}")
            seen.add(task.id)

        if seen and next_id <= max(seen):
            raise self._corrupt("'next_id' must be greater than every task id")

    def _corrupt(self, reason: str) -> CorruptStorageError:
        """
        Build the error for an unreadable file, in one consistent format.

        Why it returns instead of raising: callers write `raise ... from e`,
        which keeps the original error as the cause for debugging.
        """
        return CorruptStorageError(
            f"cannot read {self.path.name} ({reason}); file left untouched"
        )