"""
Business logic for the Task Tracker application.

This is the only layer that knows the rules of the domain: how IDs are
assigned, what a valid description is, when `updatedAt` changes. It does
not print anything and does not know where data is stored: it receives a
storage object and a clock, and returns domain objects or raises
domain exceptions. The CLI decides how to show results; the storage
decides how to persist them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol

from task_tracker.errors import TaskNotFoundError, ValidationError
from task_tracker.models import Status, Task

MAX_DESCRIPTION_LENGTH = 200
"""Upper bound for a "short description", as defined in the README contract."""

Clock = Callable[[], datetime]
"""A function that returns the current time. Injected so tests can freeze it."""


class Storage(Protocol):
    """
    What the service needs from a storage backend.

    Why a Protocol: the service depends on this small interface, not on a
    concrete class. `JsonTaskStorage` satisfies it, and so does an
    in-memory fake in the tests, without inheriting from anything
    (structural typing). Swapping JSON for SQLite later touches no code here.

    The data shape is the one in the README:
        {"version": int, "next_id": int, "tasks": [task dicts]}
    """

    def load(self) -> dict:
        """Return the current data. A store with no file yet is empty."""
        ...

    def save(self, data: dict) -> None:
        """Persist the data, replacing what was stored before."""
        ...


@dataclass(frozen=True)
class Change:
    """
    Result of an operation that may or may not modify a task.

    Why it exists: the contract has a no-op rule (same description or same
    status changes nothing). The CLI needs to know which case happened to
    print "marked as done" or "is already done". Returning a flag is
    clearer than raising an exception for a case that is not an error.

    Attributes:
        task: The task after the operation.
        changed: True if something was actually modified and saved.
    """

    task: Task
    changed: bool


def utc_now() -> datetime:
    """
    Default clock: current UTC time truncated to whole seconds.

    Why truncate: storage keeps second precision. If the in-memory Task
    kept microseconds, the object returned by `add` would differ from the
    same task loaded back from disk. Truncating here keeps both identical.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


class TaskService:
    """
    Use cases of the application: add, update, delete, mark and list.

    Every public method follows the same shape: load, validate, change,
    save, return. Each call reads fresh data from storage, so the service
    holds no state between calls and never works with a stale copy.
    """

    def __init__(self, storage: Storage, clock: Clock = utc_now) -> None:
        """
        Wire the service to its dependencies.

        Args:
            storage: Backend that loads and saves the raw data.
            clock: Source of the current time. Defaults to UTC now.

        Why inject both: dependency injection makes the service testable
        without touching the disk or the real clock. Tests pass a fake
        storage and a fixed time and get fast, deterministic results.
        """
        self._storage = storage
        self._clock = clock

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, description: str) -> Task:
        """
        Create a new task with status `todo`.

        Why `next_id` instead of `max(id) + 1`: with `max`, deleting the
        last task and adding a new one would reuse its ID, so "task 5"
        would silently mean two different things over time. The contract
        says IDs are never reused.

        Args:
            description: What needs to be done.

        Returns:
            The created task.

        Raises:
            ValidationError: The description is empty or too long.
        """
        clean = self._validate_description(description)
        data = self._storage.load()
        now = self._clock()

        task = Task(
            id=data["next_id"],
            description=clean,
            status=Status.TODO,
            created_at=now,
            updated_at=now,
        )
        data["tasks"].append(task.to_dict())
        data["next_id"] += 1
        self._storage.save(data)
        return task

    def update(self, task_id: int, description: str) -> Change:
        """
        Change the description of an existing task.

        Why validate before loading: invalid input fails fast, without
        reading the file at all.

        Args:
            task_id: ID of the task to update.
            description: New description.

        Returns:
            A Change. `changed` is False if the description was the same,
            and in that case nothing is saved and `updatedAt` stays as is.

        Raises:
            ValidationError: The description is empty or too long.
            TaskNotFoundError: No task has that ID.
        """
        clean = self._validate_description(description)
        return self._modify(task_id, description=clean)

    def set_status(self, task_id: int, status: Status) -> Change:
        """
        Move a task to another status.

        Why one method and not `mark_done` + `mark_in_progress`: both
        would be the same code with a different constant. The CLI maps
        each command to a status; the rule lives in one place (DRY).

        Args:
            task_id: ID of the task.
            status: Target status.

        Returns:
            A Change. `changed` is False if the task already had that status.

        Raises:
            TaskNotFoundError: No task has that ID.
        """
        return self._modify(task_id, status=status)

    def delete(self, task_id: int) -> Task:
        """
        Remove a task permanently.

        Why `next_id` is not touched: the deleted ID must never come back.

        Args:
            task_id: ID of the task to delete.

        Returns:
            The deleted task, so the caller can report what was removed.

        Raises:
            TaskNotFoundError: No task has that ID.
        """
        data = self._storage.load()
        index = self._find_index(data, task_id)
        removed = Task.from_dict(data["tasks"].pop(index))
        self._storage.save(data)
        return removed

    def list_tasks(self, status: Status | None = None) -> list[Task]:
        """
        Return tasks sorted by ID, optionally filtered by status.

        Why sort here and not trust the file order: the contract promises
        ID order. The file is normally sorted, but someone may have edited
        it by hand; sorting makes the output correct either way.

        Why it never saves: listing is a read. A read that writes could
        create the file or change it, which the contract forbids.

        Args:
            status: If given, only tasks with this status are returned.

        Returns:
            A new list of tasks. Empty if there are none.
        """
        data = self._storage.load()
        tasks = [Task.from_dict(raw) for raw in data["tasks"]]
        if status is not None:
            tasks = [t for t in tasks if t.status is status]
        return sorted(tasks, key=lambda t: t.id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _modify(self, task_id: int, **changes: object) -> Change:
        """
        Apply field changes to one task, honoring the no-op rule.

        Why it exists: `update` and `set_status` follow exactly the same
        steps (find, compare, stamp `updated_at`, save). Writing them once
        guarantees both obey the contract in the same way.

        Why `dataclasses.replace`: it builds a new Task instead of mutating
        the loaded one, so the "before" and "after" versions can be
        compared safely.
        """
        data = self._storage.load()
        index = self._find_index(data, task_id)
        current = Task.from_dict(data["tasks"][index])

        candidate = replace(current, **changes)
        if candidate == current:
            return Change(task=current, changed=False)

        updated = replace(candidate, updated_at=self._clock())
        data["tasks"][index] = updated.to_dict()
        self._storage.save(data)
        return Change(task=updated, changed=True)

    @staticmethod
    def _find_index(data: dict, task_id: int) -> int:
        """
        Return the position of a task in the raw list.

        Why an index and not the dict: callers need to replace or remove
        the item in place, and the index lets them do it in one step.

        Raises:
            TaskNotFoundError: No task has that ID.
        """
        for index, raw in enumerate(data["tasks"]):
            if raw["id"] == task_id:
                return index
        raise TaskNotFoundError(task_id)

    @staticmethod
    def _validate_description(description: str) -> str:
        """
        Normalize and validate a description.

        Why strip first: "  Buy milk  " and "Buy milk" are the same task
        for a human. Validating after stripping also rejects inputs made
        only of spaces.

        Why a static method: it depends only on its argument, not on the
        service's state. It is a pure function that is trivial to test.

        Returns:
            The description without leading or trailing whitespace.

        Raises:
            ValidationError: Empty after stripping, or over the length limit.
        """
        clean = description.strip()
        if not clean:
            raise ValidationError("description cannot be empty")
        if len(clean) > MAX_DESCRIPTION_LENGTH:
            raise ValidationError(f"description exceeds {MAX_DESCRIPTION_LENGTH} characters")
        return clean
