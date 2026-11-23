"""Unit tests for TaskService, using an in-memory storage and a fixed clock."""

import unittest
from datetime import datetime, timedelta, timezone

from task_tracker.errors import TaskNotFoundError, ValidationError
from task_tracker.models import Status
from task_tracker.service import MAX_DESCRIPTION_LENGTH, TaskService

T0 = datetime(2026, 11, 22, 15, 0, 0, tzinfo=timezone.utc)


class InMemoryStorage:
    """Fake storage: same interface as JsonTaskStorage, no disk."""

    def __init__(self):
        self.data = {"version": 1, "next_id": 1, "tasks": []}
        self.saves = 0

    def load(self):
        return self.data

    def save(self, data):
        self.data = data
        self.saves += 1


class FakeClock:
    """A clock the test can move forward."""

    def __init__(self, start=T0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds=60):
        self.now += timedelta(seconds=seconds)


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.storage = InMemoryStorage()
        self.clock = FakeClock()
        self.service = TaskService(self.storage, clock=self.clock)


class TestAdd(ServiceTestCase):
    def test_first_task_gets_id_1(self):
        self.assertEqual(self.service.add("Buy groceries").id, 1)

    def test_ids_increment(self):
        self.service.add("A")
        self.assertEqual(self.service.add("B").id, 2)

    def test_new_task_is_todo_with_equal_timestamps(self):
        task = self.service.add("A")
        self.assertIs(task.status, Status.TODO)
        self.assertEqual(task.created_at, T0)
        self.assertEqual(task.updated_at, T0)

    def test_task_is_saved(self):
        self.service.add("A")
        self.assertEqual(len(self.storage.data["tasks"]), 1)
        self.assertEqual(self.storage.data["next_id"], 2)

    def test_description_is_stripped(self):
        self.assertEqual(self.service.add("  Buy milk  ").description, "Buy milk")

    def test_empty_description_raises(self):
        for value in ["", "   "]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.service.add(value)

    def test_description_length_limit(self):
        self.service.add("x" * MAX_DESCRIPTION_LENGTH)
        with self.assertRaises(ValidationError):
            self.service.add("x" * (MAX_DESCRIPTION_LENGTH + 1))

    def test_invalid_input_does_not_save(self):
        with self.assertRaises(ValidationError):
            self.service.add("")
        self.assertEqual(self.storage.saves, 0)


class TestUpdate(ServiceTestCase):
    def test_changes_description_and_updated_at_only(self):
        self.service.add("A")
        self.clock.advance()
        change = self.service.update(1, "B")
        self.assertTrue(change.changed)
        self.assertEqual(change.task.description, "B")
        self.assertEqual(change.task.created_at, T0)
        self.assertEqual(change.task.updated_at, self.clock.now)

    def test_same_description_is_noop(self):
        self.service.add("A")
        saves = self.storage.saves
        self.clock.advance()
        change = self.service.update(1, "  A ")
        self.assertFalse(change.changed)
        self.assertEqual(change.task.updated_at, T0)
        self.assertEqual(self.storage.saves, saves)

    def test_unknown_id_raises(self):
        with self.assertRaises(TaskNotFoundError):
            self.service.update(99, "B")


class TestSetStatus(ServiceTestCase):
    def test_changes_status_and_updated_at(self):
        self.service.add("A")
        self.clock.advance()
        change = self.service.set_status(1, Status.DONE)
        self.assertTrue(change.changed)
        self.assertIs(change.task.status, Status.DONE)
        self.assertEqual(change.task.updated_at, self.clock.now)

    def test_same_status_is_noop(self):
        self.service.add("A")
        self.clock.advance()
        change = self.service.set_status(1, Status.TODO)
        self.assertFalse(change.changed)
        self.assertEqual(change.task.updated_at, T0)

    def test_unknown_id_raises(self):
        with self.assertRaises(TaskNotFoundError):
            self.service.set_status(99, Status.DONE)


class TestDelete(ServiceTestCase):
    def test_removes_task(self):
        self.service.add("A")
        self.assertEqual(self.service.delete(1).description, "A")
        self.assertEqual(self.service.list_tasks(), [])

    def test_ids_are_never_reused(self):
        self.service.add("A")
        self.service.add("B")
        self.service.delete(2)
        self.assertEqual(self.service.add("C").id, 3)

    def test_unknown_id_raises(self):
        with self.assertRaises(TaskNotFoundError):
            self.service.delete(99)


class TestList(ServiceTestCase):
    def setUp(self):
        super().setUp()
        for name in ["A", "B", "C"]:
            self.service.add(name)
        self.service.set_status(2, Status.IN_PROGRESS)
        self.service.set_status(3, Status.DONE)

    def test_lists_all_sorted_by_id(self):
        self.storage.data["tasks"].reverse()
        self.assertEqual([t.id for t in self.service.list_tasks()], [1, 2, 3])

    def test_filters_by_status(self):
        cases = {Status.TODO: [1], Status.IN_PROGRESS: [2], Status.DONE: [3]}
        for status, ids in cases.items():
            with self.subTest(status=status.value):
                self.assertEqual([t.id for t in self.service.list_tasks(status)], ids)

    def test_listing_never_saves(self):
        saves = self.storage.saves
        self.service.list_tasks()
        self.assertEqual(self.storage.saves, saves)


if __name__ == "__main__":
    unittest.main()