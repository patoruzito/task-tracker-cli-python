"""Integration tests for JsonTaskStorage, using a real temporary directory."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from task_tracker.errors import (
    CorruptStorageError,
    StorageAccessError,
    UnsupportedSchemaError,
)
from task_tracker.models import Status
from task_tracker.service import TaskService
from task_tracker.storage import (
    ENV_VAR,
    SCHEMA_VERSION,
    JsonTaskStorage,
    empty_state,
    resolve_path,
)

TASK = {
    "id": 1,
    "description": "Buy groceries",
    "status": "todo",
    "createdAt": "2026-11-22T15:24:00+00:00",
    "updatedAt": "2026-11-22T15:24:00+00:00",
}


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "tasks.json"
        self.storage = JsonTaskStorage(self.path)

    def write_raw(self, content):
        if not isinstance(content, str):
            content = json.dumps(content)
        self.path.write_text(content, encoding="utf-8")

    def assert_untouched(self, original):
        self.assertEqual(self.path.read_text(encoding="utf-8"), original)


class TestMissingFile(StorageTestCase):
    def test_load_returns_empty_state(self):
        self.assertEqual(self.storage.load(), empty_state())

    def test_load_does_not_create_file(self):
        self.storage.load()
        self.assertFalse(self.path.exists())

    def test_save_creates_file(self):
        self.storage.save(empty_state())
        self.assertTrue(self.path.exists())


class TestRoundTrip(StorageTestCase):
    def test_save_then_load(self):
        data = {"version": 1, "next_id": 2, "tasks": [TASK]}
        self.storage.save(data)
        self.assertEqual(self.storage.load(), data)

    def test_file_is_utf8_pretty_json(self):
        task = {**TASK, "description": "Comprar café ☕"}
        self.storage.save({"version": 1, "next_id": 2, "tasks": [task]})
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("café ☕", text)  # not escaped as é
        self.assertIn('\n  "version": 1', text)  # 2-space indent


class TestAtomicWrite(StorageTestCase):
    def test_failure_during_write_keeps_old_file(self):
        self.storage.save({"version": 1, "next_id": 2, "tasks": [TASK]})
        original = self.path.read_text(encoding="utf-8")

        with mock.patch("task_tracker.storage.json.dump", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.storage.save(empty_state())

        self.assert_untouched(original)

    def test_failure_leaves_no_temp_files(self):
        with mock.patch("task_tracker.storage.json.dump", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.storage.save(empty_state())
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_success_leaves_no_temp_files(self):
        self.storage.save(empty_state())
        self.assertEqual([p.name for p in self.dir.iterdir()], ["tasks.json"])


class TestCorruptFile(StorageTestCase):
    CASES = {
        "invalid json": "{not json",
        "empty file": "",
        "top level is a string": '"hello"',
        "missing version": {"next_id": 1, "tasks": []},
        "version is a string": {"version": "1", "next_id": 1, "tasks": []},
        "next_id is a bool": {"version": 1, "next_id": True, "tasks": []},
        "tasks is not a list": {"version": 1, "next_id": 1, "tasks": {}},
        "task is not an object": {"version": 1, "next_id": 2, "tasks": [1]},
        "task has bad status": {
            "version": 1, "next_id": 2, "tasks": [{**TASK, "status": "pending"}]
        },
        "duplicate ids": {"version": 1, "next_id": 2, "tasks": [TASK, TASK]},
        "next_id not above ids": {"version": 1, "next_id": 1, "tasks": [TASK]},
    }

    def test_rejected_and_left_untouched(self):
        for name, content in self.CASES.items():
            with self.subTest(name):
                self.write_raw(content)
                original = self.path.read_text(encoding="utf-8")
                with self.assertRaises(CorruptStorageError):
                    self.storage.load()
                self.assert_untouched(original)

    def test_invalid_utf8(self):
        self.path.write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(CorruptStorageError):
            self.storage.load()

    def test_message_names_the_file(self):
        self.write_raw("{not json")
        with self.assertRaises(CorruptStorageError) as ctx:
            self.storage.load()
        self.assertIn("tasks.json", str(ctx.exception))
        self.assertIn("left untouched", str(ctx.exception))


class TestSchemaVersion(StorageTestCase):
    def test_newer_version_is_refused(self):
        self.write_raw({"version": SCHEMA_VERSION + 1, "next_id": 1, "tasks": []})
        with self.assertRaises(UnsupportedSchemaError):
            self.storage.load()

    def test_legacy_list_is_migrated_in_memory(self):
        self.write_raw([TASK, {**TASK, "id": 4}])
        original = self.path.read_text(encoding="utf-8")

        data = self.storage.load()

        self.assertEqual(data["version"], SCHEMA_VERSION)
        self.assertEqual(data["next_id"], 5)
        self.assertEqual(len(data["tasks"]), 2)
        self.assert_untouched(original)  # a read never writes


class TestAccessErrors(StorageTestCase):
    def test_missing_parent_directory(self):
        storage = JsonTaskStorage(self.dir / "nope" / "tasks.json")
        with self.assertRaises(StorageAccessError):
            storage.save(empty_state())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores permissions")
    def test_read_only_directory(self):
        self.dir.chmod(0o500)
        self.addCleanup(self.dir.chmod, 0o700)
        with self.assertRaises(StorageAccessError):
            self.storage.save(empty_state())


class TestResolvePath(unittest.TestCase):
    def test_defaults_to_current_directory(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_path(), Path.cwd() / "tasks.json")

    def test_env_var_overrides(self):
        with mock.patch.dict(os.environ, {ENV_VAR: "/tmp/custom.json"}):
            self.assertEqual(resolve_path(), Path("/tmp/custom.json"))


class TestWithService(StorageTestCase):
    """The real storage plugged into the real service."""

    def test_tasks_survive_a_new_service_instance(self):
        TaskService(self.storage).add("Buy groceries")
        TaskService(self.storage).set_status(1, Status.DONE)

        tasks = TaskService(JsonTaskStorage(self.path)).list_tasks()

        self.assertEqual(len(tasks), 1)
        self.assertIs(tasks[0].status, Status.DONE)

    def test_listing_does_not_create_file(self):
        TaskService(self.storage).list_tasks()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()