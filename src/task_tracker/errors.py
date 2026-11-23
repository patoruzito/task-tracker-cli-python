"""
Custom exceptions for the Task Tracker application.

All application errors inherit from TaskTrackerError, so the CLI can
catch them in a single place and map them to messages and exit codes.

Hierarchy:
    TaskTrackerError
    ├── ValidationError         user input breaks a business rule
    ├── TaskNotFoundError       no task with the requested ID
    ├── InvalidTaskDataError    a dict cannot become a Task
    └── StorageError            anything about the tasks file
        ├── CorruptStorageError     unreadable or invalid content
        ├── UnsupportedSchemaError  written by a newer version
        └── StorageAccessError      the OS refused to read or write
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


class StorageError(TaskTrackerError):
    """Base class for problems with the tasks file."""


class CorruptStorageError(StorageError):
    """The tasks file cannot be parsed or does not match the schema."""


class UnsupportedSchemaError(StorageError):
    """The tasks file uses a schema version newer than this program."""


class StorageAccessError(StorageError):
    """The operating system refused to read or write the tasks file."""