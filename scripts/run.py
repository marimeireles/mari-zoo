#!/usr/bin/env python3
"""Simple script to run zoo-eval tasks."""

import asyncio
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zoo_eval.models import load_tasks
from zoo_eval.runner import RunConfig, TaskRunner
from zoo_eval.zoo import Zoo


async def main():
    # Load a few sample tasks
    config_path = Path(__file__).parent.parent / "configs" / "test_webarena.raw.json"
    tasks = load_tasks(config_path, limit=3)

    print(f"Loaded {len(tasks)} tasks")
    for t in tasks:
        print(f"  Task {t.task_id}: {t.intent[:60]}...")

    # Check Zoo
    zoo = Zoo()
    if not zoo.is_running():
        print("Zoo is not running. Start with: npx the_zoo start")
        return

    print("\nZoo is running!")

    # Quick test: fetch a page
    try:
        content = zoo.fetch_page("https://home.zoo")
        print(f"Fetched home.zoo: {len(content)} bytes")
    except Exception as e:
        print(f"Error fetching: {e}")


if __name__ == "__main__":
    asyncio.run(main())
