"""
Data models for the Task Tracker application.

This module defines the core domain entities and serialization logic
used to represent and persist tasks.
"""
# models.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class Status(str, Enum):
    """
    Represents the valid workflow states for a task.

    Inherits from `str` and `Enum` to allow seamless string comparisons
    and direct JSON serialization while enforcing strict state values.
    """

    TODO = "todo"
    IN_PROGRESS = "in-progress"
    DONE = "done"


@dataclass
class Task:
    """
    Represents an individual task item within the system.

    Uses the `@dataclass` decorator to automatically generate boilerplate
    special methods (`__init__`, `__repr__`, and `__eq__`) based on the
    defined type annotations.

    Attributes:
        id: Unique numeric identifier for the task.
        description: Brief summary of what needs to be done.
        status: Current lifecycle state of the task.
        created_at: Timestamp indicating when the task was created.
        update_at: Timestamp indicating the last modification to the task.
    """

    id: int
    description: str
    status: Status
    created_at: datetime
    update_at: datetime

    def to_dict(self) -> dict:
        """
        Serializes the Task instance into a JSON-compatible dictionary.

        Converts complex Python types (`Status` enum and `datetime` objects)
        into primitive strings and maps attribute names to camelCase keys.

        Returns:
            A dictionary representation of the task ready for JSON persistence.
        """
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "createdAt": self.created_at.isoformat(),
            "updateAt": self.update_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """
        Deserializes a dictionary into a new Task instance.

        Uses the `@classmethod` decorator as an alternative constructor (factory
        method), allowing instantiation directly from raw dictionary data
        without requiring an existing `Task` object.

        Args:
            data: A dictionary containing raw task fields, typically loaded
                from a JSON source.

        Returns:
            A newly instantiated `Task` object with parsed types.
        """
        return cls(
            id=data["id"],
            description=data["description"],
            status=Status(data["status"]),
            created_at=datetime.fromisoformat(data["createdAt"]),
            update_at=datetime.fromisoformat(data["updateAt"]),
        )