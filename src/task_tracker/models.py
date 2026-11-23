"""
Data models for the Task Tracker application.

This module defines the core domain entities and their serialization
logic. It knows nothing about files or the command line: it only turns
tasks into dictionaries and back.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, TypedDict

from task_tracker.errors import InvalidTaskDataError

TaskDict = dict[str, Any]
"""A task as stored in JSON: camelCase keys and primitive values."""


class StoreData(TypedDict):
    """
    The whole content of the tasks file, as described in the README.

    Why a TypedDict: the service and the storage exchange this dict.
    Declaring its keys lets the type checker catch a typo such as
    `data["nextId"]` before any test runs.
    """

    version: int
    next_id: int
    tasks: list[TaskDict]


class Status(str, Enum):
    """
    Valid workflow states for a task.

    Inherits from `str` so values serialize to JSON directly. Always use
    `.value` to get the plain string: since Python 3.11, `str(Status.TODO)`
    returns "Status.TODO", not "todo".
    """

    TODO = "todo"
    IN_PROGRESS = "in-progress"
    DONE = "done"


@dataclass
class Task:
    """
    A single task in the system.

    Attributes:
        id: Unique numeric identifier. Never reused.
        description: Short summary of what needs to be done.
        status: Current lifecycle state of the task.
        created_at: When the task was created (timezone-aware, UTC).
        updated_at: When the task was last changed (timezone-aware, UTC).
    """

    id: int
    description: str
    status: Status
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Reject naive timestamps: the contract requires UTC with offset."""
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise InvalidTaskDataError("timestamps must be timezone-aware")

    def to_dict(self) -> TaskDict:
        """
        Serialize the task into a JSON-compatible dictionary.

        Keys follow the storage contract (camelCase) and timestamps use
        ISO 8601 with second precision.

        Returns:
            A dictionary ready for JSON persistence.
        """
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "createdAt": self.created_at.isoformat(timespec="seconds"),
            "updatedAt": self.updated_at.isoformat(timespec="seconds"),
        }

    @classmethod
    def from_dict(cls, data: TaskDict) -> "Task":
        """
        Build a Task from a dictionary loaded from storage.

        Args:
            data: Raw task fields, typically from the JSON file.

        Returns:
            A new Task with parsed types.

        Raises:
            InvalidTaskDataError: A field is missing or has an invalid value.
        """
        try:
            return cls(
                id=data["id"],
                description=data["description"],
                status=Status(data["status"]),
                created_at=datetime.fromisoformat(data["createdAt"]),
                updated_at=datetime.fromisoformat(data["updatedAt"]),
            )
        except (KeyError, ValueError, TypeError) as e:
            raise InvalidTaskDataError(f"invalid task data: {data!r}") from e
