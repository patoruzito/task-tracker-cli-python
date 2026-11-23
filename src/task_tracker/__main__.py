"""Allow running the CLI as `python -m task_tracker`."""

import sys

from task_tracker.cli import main

sys.exit(main())
