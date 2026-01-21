"""Task runner that orchestrates browser_use agent execution."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

from .auth import get_login_hint
from .evaluators import EvalResult, evaluate_task
from .models import AgentConfig, RunConfig, Task, TaskResult
from .multi_agent_runner import MultiAgentRunner
from .zoo import Zoo


@dataclass
class RunResult:
    """Complete result of a task run including evaluation."""

    task: Task
    task_result: TaskResult
    eval_results: list[EvalResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Task passes if all evaluations pass."""
        return all(e.passed for e in self.eval_results)


class TaskRunner:
    """Runs tasks using browser_use agent."""

    def __init__(
        self, zoo: Zoo, agents: list[AgentConfig], config: RunConfig | None = None
    ):
        self.zoo = zoo
        self.agents = agents
        self.config = config or RunConfig()
        self._multi_agent_runner = None

    async def setup(self):
        """Initialize browser_use components."""
        os.environ["ANONYMIZED_TELEMETRY"] = "false"
        # Create multi-agent runner
        self._multi_agent_runner = MultiAgentRunner(self.zoo, self.config)
        await self._multi_agent_runner.setup()

    async def teardown(self):
        """Clean up resources."""
        pass

    async def run_and_evaluate_batch(
        self, tasks: list[Task], universe_name: str = "unknown"
    ) -> list[RunResult]:
        """Run multiple tasks distributed across agents and evaluate results.

        Args:
            tasks: Tasks to run
            universe_name: Name of the universe (for human review file organization)
        """
        # Run all tasks with agent assignment
        task_results = await self._multi_agent_runner.run_multi_agent_tasks(
            self.agents, tasks
        )

        # Evaluate each result
        run_results = []
        for task_result in task_results:
            # Find the corresponding task
            task = next(t for t in tasks if t.task_id == task_result.task_id)
            # Get the evaluation for this specific autonomy level (falls back to default)
            evaluation = task.get_evaluation_for_level(task_result.autonomy_level)
            # Pass task and universe_name to evaluators
            eval_results = await evaluate_task(
                task_result,
                evaluation,
                task=task,
                universe_name=universe_name,
            )
            run_results.append(
                RunResult(task=task, task_result=task_result, eval_results=eval_results)
            )

        return run_results
