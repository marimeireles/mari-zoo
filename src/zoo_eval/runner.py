"""Task runner that orchestrates agent execution."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .evaluators import EvalResult, evaluate_task
from .models import AgentHarness, RunConfig, Task, TaskResult, Universe, load_universe
from .zoo import Zoo

if TYPE_CHECKING:
    from .base_agent_runner import BaseAgentRunner


def create_agent_runner(
    zoo: Zoo,
    config: RunConfig,
    universe_path: Path | None = None,
    universe: Universe | None = None,
) -> "BaseAgentRunner":
    """Factory function to create the appropriate agent runner.

    Args:
        zoo: Zoo instance for environment interaction
        config: Run configuration with harness selection
        universe_path: Path to universe config directory
        universe: Pre-loaded Universe object

    Returns:
        Appropriate runner instance based on config.harness
    """
    if config.harness == AgentHarness.CLAUDE_SDK:
        from .claude_sdk_runner import ClaudeSDKRunner

        return ClaudeSDKRunner(zoo, config, universe_path, universe)
    else:
        from .agent_runner import AgentRunner

        return AgentRunner(zoo, config, universe_path, universe)


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
    """Runs tasks using configured agent harness."""

    def __init__(
        self, zoo: Zoo, config: RunConfig | None = None, universe_path: Path | None = None, universe: Universe | None = None
    ):
        self.zoo = zoo
        self.config = config or RunConfig()
        self.universe_path = universe_path
        self.universe = universe
        self._agent_runner: "BaseAgentRunner | None" = None

    async def setup(self):
        """Initialize agent runner components."""
        os.environ["ANONYMIZED_TELEMETRY"] = "false"
        # Create agent runner based on harness config
        self._agent_runner = create_agent_runner(
            self.zoo, self.config, self.universe_path, self.universe
        )
        await self._agent_runner.setup()

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
        # Run all tasks
        task_results = await self._agent_runner.run_tasks(tasks)

        # Evaluate each result
        run_results = []
        for task_result in task_results:
            # Find the corresponding task
            task = next(t for t in tasks if t.task_id == task_result.task_id)
            # Get the evaluation for this specific autonomy level (falls back to default)
            evaluation = task.get_evaluation_for_level(task_result.autonomy_level)
            # Pass task, universe_name, and judge_model to evaluators
            eval_results = await evaluate_task(
                task_result,
                evaluation,
                task=task,
                universe_name=universe_name,
                judge_model=self.config.judge_model,
            )
            run_results.append(
                RunResult(task=task, task_result=task_result, eval_results=eval_results)
            )

        return run_results
