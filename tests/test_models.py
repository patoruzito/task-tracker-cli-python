"""Unit tests for the Task domain model."""

import unittest
from datetime import datetime, timezone

from task_tracker.errors import InvalidTaskDataError
from task_tracker.models import Status, Task

# Second precision on purpose: the contract stores seconds only.
CREATED = datetime(2026, 11, 22, 15, 24, 0, tzinfo=timezone.utc)
UPDATED = datetime(2026, 11, 22, 18, 2, 11, tzinfo=timezone.utc)


def make_task(**overrides) -> Task:
    """Build a valid Task; any field can be overridden per test."""
    fields = {
        "id": 1,
        "description": "Buy groceries",
        "status": Status.IN_PROGRESS,
        "created_at": CREATED,
        "updated_at": UPDATED,
    }
    fields.update(overrides)
    return Task(**fields)


class TestTaskRoundTrip(unittest.TestCase):
    """Task -> dict -> Task must not lose or change any data."""

    def test_round_trip_preserves_all_fields(self):
        # Arrange
        original = make_task()

        # Act
        restored = Task.from_dict(original.to_dict())

        # Assert
        self.assertEqual(restored, original)

    def test_round_trip_preserves_types(self):
        restored = Task.from_dict(make_task().to_dict())

        self.assertIsInstance(restored.status, Status)
        self.assertIsInstance(restored.created_at, datetime)
        self.assertIsNotNone(restored.created_at.tzinfo)

    def test_round_trip_works_for_every_status(self):
        for status in Status:
            with self.subTest(status=status.value):
                original = make_task(status=status)
                self.assertEqual(Task.from_dict(original.to_dict()), original)

    def test_round_trip_preserves_unicode_description(self):
        original = make_task(description='Comprar "pan" y café ☕')
        self.assertEqual(Task.from_dict(original.to_dict()), original)

    def test_to_dict_keys_match_contract(self):
        # A round trip can't catch a misspelled key (to_dict and from_dict
        # would share the typo), so check against the README contract.
        self.assertEqual(
            set(make_task().to_dict()),
            {"id", "description", "status", "createdAt", "updatedAt"},
        )


class TestTaskInvalidStatus(unittest.TestCase):
    """from_dict must reject statuses outside the contract."""

    def setUp(self):
        self.data = make_task().to_dict()

    def test_unknown_status_raises_invalid_task_data_error(self):
        self.data["status"] = "pending"

        with self.assertRaises(InvalidTaskDataError):
            Task.from_dict(self.data)

    def test_status_is_case_sensitive(self):
        self.data["status"] = "DONE"

        with self.assertRaises(InvalidTaskDataError):
            Task.from_dict(self.data)

    def test_original_error_is_kept_as_cause(self):
        self.data["status"] = "pending"

        with self.assertRaises(InvalidTaskDataError) as ctx:
            Task.from_dict(self.data)

        self.assertIsInstance(ctx.exception.__cause__, ValueError)


if __name__ == "__main__":
    unittest.main()
