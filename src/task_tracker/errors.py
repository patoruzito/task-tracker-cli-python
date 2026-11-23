"""
Custom exceptions for the Task Tracker application.

All application errors inherit from TaskTrackerError, so the CLI can
catch them in a single place and map them to messages and exit codes.
"""


class TaskTrackerError(Exception):
    """Base class for all application errors."""

    exit_code = 1


class ValidationError(TaskTrackerError):
    """User input breaks a business rule (e.g. empty description)."""


class TaskNotFoundError(TaskTrackerError):
    """No task exists with the requested ID."""

    def __init__(self, task_id: int):
        super().__init__(f"task {task_id} not found")
        self.task_id = task_id


class InvalidTaskDataError(TaskTrackerError):
    """Raw data cannot be turned into a valid Task."""


class CorruptStorageError(TaskTrackerError):
    """The storage file cannot be read or does not match the schema."""