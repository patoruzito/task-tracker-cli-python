import unittest
from datetime import datetime, timezone

from task_tracker.service import TaskService

FIXED_NOW = datetime(2026, 11, 22, 15, 0, 0, tzinfo=timezone.utc)


class InMemoryStorage:
    def __init__(self):
        self.data = {"version": 1, "next_id": 1, "tasks": []}

    def load(self):
        return self.data

    def save(self, data):
        self.data = data


class TestAdd(unittest.TestCase):
    def setUp(self):
        self.storage = InMemoryStorage()
        self.service = TaskService(self.storage, clock=lambda: FIXED_NOW)

    def test_first_task_gets_id_1(self):
        task = self.service.add("Buy groceries")
        self.assertEqual(task.id, 1)