"""
Command line interface for the Task Tracker application.

This is the outermost layer: it turns command line arguments into calls
to `TaskService` and turns the results into text and exit codes. It
holds no business rules. If a rule is needed here, it belongs in the
service.

Output contract (see README):
    stdout  results
    stderr  errors, prefixed with "error: "
    exit 0  success, including no-ops
    exit 1  runtime error (task not found, corrupt file, ...)
    exit 2  incorrect usage (handled by argparse)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version

from task_tracker.errors import TaskTrackerError
from task_tracker.models import Status, Task
from task_tracker.service import TaskService
from task_tracker.storage import JsonTaskStorage, resolve_path

PROG = "task-cli"

EXIT_OK = 0
EXIT_INTERRUPTED = 130
"""Shell convention for "terminated by Ctrl+C" (128 + SIGINT)."""

Handler = Callable[[TaskService, argparse.Namespace], int]


# ----------------------------------------------------------------------
# Argument types
# ----------------------------------------------------------------------


def task_id(value: str) -> int:
    """
    Parse a task ID from the command line.

    Why a custom argparse type: argparse then reports a bad ID as a
    usage error (exit 2) with its standard message, exactly like a
    missing argument. The service only ever receives valid integers.

    Raises:
        argparse.ArgumentTypeError: Not a positive integer.
    """
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid task id: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"invalid task id: {value!r}")
    return number


# ----------------------------------------------------------------------
# Command handlers
# ----------------------------------------------------------------------
# Why one small function per command: each one maps a single command to
# a single service call and prints the result. Errors are not handled
# here; they bubble up to `main`, the only place that turns exceptions
# into messages. Each handler returns its exit code.


def cmd_add(service: TaskService, args: argparse.Namespace) -> int:
    task = service.add(args.description)
    print(f"Task added successfully (ID: {task.id})")
    return EXIT_OK


def cmd_update(service: TaskService, args: argparse.Namespace) -> int:
    change = service.update(args.id, args.description)
    if change.changed:
        print(f"Task {args.id} updated successfully")
    else:
        print(f"Task {args.id} already has that description")
    return EXIT_OK


def cmd_delete(service: TaskService, args: argparse.Namespace) -> int:
    service.delete(args.id)
    print(f"Task {args.id} deleted successfully")
    return EXIT_OK


def make_mark_handler(status: Status) -> Handler:
    """
    Build the handler for a `mark-*` command.

    Why a factory: `mark-in-progress` and `mark-done` differ only in the
    target status. One factory keeps them identical in behavior and makes
    a future `mark-todo` a one-line addition.
    """

    def handler(service: TaskService, args: argparse.Namespace) -> int:
        change = service.set_status(args.id, status)
        if change.changed:
            print(f"Task {args.id} marked as {status.value}")
        else:
            print(f"Task {args.id} is already {status.value}")
        return EXIT_OK

    return handler


def cmd_list(service: TaskService, args: argparse.Namespace) -> int:
    status = Status(args.status) if args.status else None
    tasks = service.list_tasks(status)
    if not tasks:
        print("No tasks found")
    else:
        print(format_tasks(tasks))
    return EXIT_OK


def format_tasks(tasks: Sequence[Task]) -> str:
    """
    Render tasks as an aligned table.

    Why a separate pure function: formatting is the part most likely to
    change (colors, more columns, a --json flag). Isolated, it can be
    tested and replaced without touching any command.

    Why line breaks in descriptions are flattened: one task must be
    exactly one row, or the table falls apart.
    """
    lines = [f"{'ID':<5}{'STATUS':<14}DESCRIPTION"]
    for task in tasks:
        description = " ".join(task.description.split())
        lines.append(f"{task.id:<5}{task.status.value:<14}{description}")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------


def package_version() -> str:
    """Installed version, read from package metadata (single source: pyproject)."""
    try:
        return version("task-tracker-cli")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    """
    Define every command, argument and help text.

    Why subparsers with `set_defaults(handler=...)`: each command carries
    its own handler, so `main` dispatches with one call instead of an
    if/elif chain that grows with every command.

    Why `choices` on the list filter: argparse rejects an invalid status
    with a clear usage message (exit 2) before any code runs.
    """
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Track what you need to do, what you are doing and what you have done.",
        epilog="Tasks are stored in ./tasks.json (override with TASK_CLI_FILE).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")

    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    add = sub.add_parser("add", help="add a new task")
    add.add_argument("description", help="what needs to be done (quote it if it has spaces)")
    add.set_defaults(handler=cmd_add)

    update = sub.add_parser("update", help="change a task's description")
    update.add_argument("id", type=task_id, help="task ID")
    update.add_argument("description", help="new description")
    update.set_defaults(handler=cmd_update)

    delete = sub.add_parser("delete", help="delete a task")
    delete.add_argument("id", type=task_id, help="task ID")
    delete.set_defaults(handler=cmd_delete)

    for status in (Status.IN_PROGRESS, Status.DONE):
        mark = sub.add_parser(f"mark-{status.value}", help=f"mark a task as {status.value}")
        mark.add_argument("id", type=task_id, help="task ID")
        mark.set_defaults(handler=make_mark_handler(status))

    lst = sub.add_parser("list", help="list tasks, optionally filtered by status")
    lst.add_argument(
        "status",
        nargs="?",
        choices=[s.value for s in Status],
        help="show only tasks with this status",
    )
    lst.set_defaults(handler=cmd_list)

    return parser


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the CLI and return the exit code.

    Why `argv` is a parameter: tests call `main(["add", "x"])` directly,
    without spawning a process or patching `sys.argv`.

    Why it returns instead of calling `sys.exit`: the caller decides.
    The installed `task-cli` script and `python -m task_tracker` pass
    the value to `sys.exit`; tests just assert on it.

    Why the service is built here: this is the composition root, the one
    place where the concrete pieces (JSON storage, real clock, file path)
    are chosen and wired together. Every inner layer only receives them.

    Why this is the only `except`: every expected failure is a
    TaskTrackerError, so one handler maps all of them to stderr and an
    exit code, and no traceback ever reaches the user.
    """
    args = build_parser().parse_args(argv)  # exits with 2 on usage errors
    service = TaskService(JsonTaskStorage(resolve_path()))
    handler: Handler = args.handler  # argparse attributes are untyped
    try:
        return handler(service, args)
    except TaskTrackerError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
