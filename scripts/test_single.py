#!/usr/bin/env python3
"""Test a single task end-to-end without running the full agent."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zoo_eval.evaluators import evaluate_task
from zoo_eval.models import Task, TaskResult, load_tasks
from zoo_eval.zoo import Zoo


def test_evaluators():
    """Test evaluators with mock results."""
    config_path = Path(__file__).parent.parent / "configs" / "test_webarena.raw.json"
    tasks = load_tasks(config_path, limit=5)

    print("Testing evaluators with mock results:\n")

    # Task 0: exact match for "Quest Lumaflex™ Band"
    task = tasks[0]
    print(f"Task {task.task_id}: {task.intent}")
    print(f"  Expected: {task.evaluation.reference_answers}")

    # Test with correct answer
    result = TaskResult(
        task_id=task.task_id,
        success=True,
        agent_answer="The top-1 best-selling product in 2022 is Quest Lumaflex™ Band",
    )
    evals = evaluate_task(result, task.evaluation)
    for e in evals:
        status = "PASS" if e.passed else "FAIL"
        print(f"  [{status}] {e.eval_type.value}: {e.details}")

    # Test with wrong answer
    result_wrong = TaskResult(
        task_id=task.task_id,
        success=True,
        agent_answer="The top product is iPhone",
    )
    evals = evaluate_task(result_wrong, task.evaluation)
    for e in evals:
        status = "PASS" if e.passed else "FAIL"
        print(f"  [Wrong answer test - {status}] {e.eval_type.value}: {e.details}")

    print("\n---")

    # Task 3: must_include for multiple products
    task = tasks[3]
    print(f"\nTask {task.task_id}: {task.intent}")
    print(f"  Must include: {task.evaluation.reference_answers.must_include}")

    result = TaskResult(
        task_id=task.task_id,
        success=True,
        agent_answer="Quest Lumaflex™ Band and Sprite Stasis Ball 65 cm are the top sellers",
    )
    evals = evaluate_task(result, task.evaluation)
    for e in evals:
        status = "PASS" if e.passed else "FAIL"
        print(f"  [{status}] {e.eval_type.value}: {e.details}")


async def test_zoo_fetch():
    """Test fetching pages through Zoo proxy."""
    zoo = Zoo()

    if not zoo.is_running():
        print("Zoo is not running!")
        return

    print("\nTesting Zoo page fetches:")

    # Test onestopshop (shopping)
    url = zoo.resolve_url("__SHOPPING__")
    print(f"  Fetching {url}...")
    try:
        content = zoo.fetch_page(url)
        print(f"    Got {len(content)} bytes")
    except Exception as e:
        print(f"    Error: {e}")

    # Test postmill (reddit)
    url = zoo.resolve_url("__REDDIT__")
    print(f"  Fetching {url}...")
    try:
        content = zoo.fetch_page(url)
        print(f"    Got {len(content)} bytes")
    except Exception as e:
        print(f"    Error: {e}")

    # Test gitea (gitlab)
    url = zoo.resolve_url("__GITLAB__")
    print(f"  Fetching {url}...")
    try:
        content = zoo.fetch_page(url)
        print(f"    Got {len(content)} bytes")
    except Exception as e:
        print(f"    Error: {e}")


if __name__ == "__main__":
    test_evaluators()
    asyncio.run(test_zoo_fetch())
