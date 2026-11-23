"""
Tests for the command line interface.

Two levels:
- in-process: call `main(argv)` and capture stdout/stderr. Fast, and
  they check every message and exit code in the README contract.
- end-to-end: run `python -m task_tracker` in a real subprocess. Slower,
  so only a few; they prove the whole program works as a user sees it.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import task_tracker
from task_tracker.cli import main
from task_tracker.storage import ENV_VAR


class CliTestCase(unittest.TestCase):
    """Each test gets its own empty tasks file via TASK_CLI_FILE."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "tasks.json"
        env = mock.patch.dict(os.environ, {ENV_VAR: str(self.path)})
        env.start()
        self.addCleanup(env.stop)

    def run_cli(self, *argv):
        """Run main() and return (exit_code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(list(argv))
            except SystemExit as e:  # argparse exits on usage errors
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def assert_ok(self, argv, expected_stdout):
        code, out, err = self.run_cli(*argv)
        self.assertEqual((code, err), (0, ""), msg=err)
        self.assertEqual(out, expected_stdout)


class TestCommands(CliTestCase):
    def test_add(self):
        self.assert_ok(["add", "Buy groceries"], "Task added successfully (ID: 1)\n")

    def test_update(self):
        self.run_cli("add", "A")
        self.assert_ok(["update", "1", "B"], "Task 1 updated successfully\n")

    def test_update_same_description(self):
        self.run_cli("add", "A")
        self.assert_ok(["update", "1", "A"], "Task 1 already has that description\n")

    def test_delete(self):
        self.run_cli("add", "A")
        self.assert_ok(["delete", "1"], "Task 1 deleted successfully\n")

    def test_mark_commands(self):
        self.run_cli("add", "A")
        self.assert_ok(["mark-in-progress", "1"], "Task 1 marked as in-progress\n")
        self.assert_ok(["mark-done", "1"], "Task 1 marked as done\n")
        self.assert_ok(["mark-done", "1"], "Task 1 is already done\n")

    def test_list_all(self):
        self.run_cli("add", "Buy groceries")
        self.run_cli("add", "Write README")
        self.run_cli("mark-done", "1")
        self.assert_ok(
            ["list"],
            "ID   STATUS        DESCRIPTION\n"
            "1    done          Buy groceries\n"
            "2    todo          Write README\n",
        )

    def test_list_filters(self):
        self.run_cli("add", "A")
        self.run_cli("add", "B")
        self.run_cli("mark-in-progress", "2")
        for status, expected_ids in {"todo": ["1"], "in-progress": ["2"]}.items():
            with self.subTest(status=status):
                _, out, _ = self.run_cli("list", status)
                ids = [line.split()[0] for line in out.splitlines()[1:]]
                self.assertEqual(ids, expected_ids)

    def test_list_empty(self):
        self.assert_ok(["list"], "No tasks found\n")
        self.assert_ok(["list", "done"], "No tasks found\n")

    def test_list_flattens_line_breaks(self):
        self.run_cli("add", "line one\nline two")
        _, out, _ = self.run_cli("list")
        self.assertEqual(len(out.splitlines()), 2)  # header + one row


class TestRuntimeErrors(CliTestCase):
    """Exit 1, message on stderr with the 'error: ' prefix, nothing on stdout."""

    def assert_error(self, argv, message):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, f"error: {message}\n")

    def test_task_not_found(self):
        for argv in (["update", "99", "x"], ["delete", "99"], ["mark-done", "99"]):
            with self.subTest(argv=argv):
                self.assert_error(argv, "task 99 not found")

    def test_empty_description(self):
        self.assert_error(["add", "   "], "description cannot be empty")

    def test_corrupt_file_is_reported_and_untouched(self):
        self.path.write_text("{broken", encoding="utf-8")
        code, _, err = self.run_cli("add", "A")
        self.assertEqual(code, 1)
        self.assertIn("left untouched", err)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{broken")


class TestUsageErrors(CliTestCase):
    """Exit 2, argparse usage message on stderr."""

    CASES = {
        "no command": [],
        "unknown command": ["borrar", "1"],
        "add without description": ["add"],
        "update without description": ["update", "1"],
        "non-numeric id": ["delete", "abc"],
        "zero id": ["delete", "0"],
        "negative id": ["delete", "-1"],
        "invalid list filter": ["list", "pending"],
    }

    def test_usage_errors_exit_2(self):
        for name, argv in self.CASES.items():
            with self.subTest(name):
                code, out, err = self.run_cli(*argv)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn("usage:", err)

    def test_usage_error_does_not_create_file(self):
        self.run_cli("delete", "abc")
        self.assertFalse(self.path.exists())


class TestEndToEnd(unittest.TestCase):
    """Run the real program in a subprocess, the way a user would."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cwd = Path(tmp.name)
        src = str(Path(task_tracker.__file__).resolve().parent.parent)
        self.env = {**os.environ, "PYTHONPATH": src, "PYTHONIOENCODING": "utf-8"}
        self.env.pop(ENV_VAR, None)

    def run_program(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "task_tracker", *argv],
            cwd=self.cwd, env=self.env, capture_output=True, text=True,
            encoding="utf-8", timeout=10,
        )

    def test_full_workflow_writes_contract_json(self):
        self.assertEqual(self.run_program("add", "Comprar café ☕").returncode, 0)
        self.assertEqual(self.run_program("mark-done", "1").returncode, 0)

        data = json.loads((self.cwd / "tasks.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["next_id"], 2)
        task = data["tasks"][0]
        self.assertEqual(
            set(task), {"id", "description", "status", "createdAt", "updatedAt"}
        )
        self.assertEqual(task["description"], "Comprar café ☕")
        self.assertEqual(task["status"], "done")

    def test_errors_never_show_a_traceback(self):
        result = self.run_program("delete", "1")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)

    def test_help_works(self):
        result = self.run_program("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("mark-in-progress", result.stdout)


if __name__ == "__main__":
    unittest.main()