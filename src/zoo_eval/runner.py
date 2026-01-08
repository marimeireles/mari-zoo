"""Task runner that orchestrates browser_use agent execution."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

from .auth import get_login_hint
from .evaluators import EvalResult, evaluate_task
from .models import RunConfig, Task, TaskResult
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

    def __init__(self, zoo: Zoo, config: RunConfig | None = None):
        self.zoo = zoo
        self.config = config or RunConfig()
        self._llm = None
        self._multi_agent_runner = None

    async def setup(self):
        """Initialize browser_use components."""
        os.environ["ANONYMIZED_TELEMETRY"] = "false"
        self._llm = self._create_llm()
        # Create multi-agent runner
        self._multi_agent_runner = MultiAgentRunner(self.zoo, self.config)
        await self._multi_agent_runner.setup()

    def _create_llm(self):
        """Create LLM based on model config."""
        from browser_use import ChatOpenAI

        model = self.config.model

        # Model aliases for convenience
        aliases = {
            "flash": "google/gemini-2.5-flash",
            "flash-lite": "google/gemini-2.5-flash-lite",
            "claude": "anthropic/claude-sonnet-4",
            "sonnet": "anthropic/claude-sonnet-4",
        }
        model = aliases.get(model, model)

        # Use OpenRouter for non-OpenAI models
        if "/" in model:
            return ChatOpenAI(
                model=model,
                base_url="https://openrouter.ai/api/v1",
                api_key=os.environ.get("OPENROUTER_API_KEY"),
            )
        else:
            return ChatOpenAI(model=model)

    async def teardown(self):
        """Clean up resources."""
        pass  # Browser is now created/destroyed per task

    async def _create_browser(self):
        """Create a fresh browser instance for a task."""
        from browser_use import Browser
        from browser_use.browser.profile import ProxySettings

        return Browser(
            headless=self.config.headless,
            proxy=ProxySettings(server=self.zoo.config.proxy_url),
            args=["--ignore-certificate-errors"],
        )

    async def run_and_evaluate(self, task: Task) -> RunResult:
        """Run a task and evaluate the result."""
        # Always use multi-agent runner
        task_result = await self._multi_agent_runner.run_multi_agent_task(task)
        eval_results = evaluate_task(task_result, task.evaluation)
        return RunResult(task=task, task_result=task_result, eval_results=eval_results)

    async def run_batch(
        self, tasks: list[Task], concurrency: int = 1
    ) -> list[RunResult]:
        """Run multiple tasks, optionally with concurrency."""
        results = []

        if concurrency == 1:
            # Sequential execution
            for task in tasks:
                result = await self.run_and_evaluate(task)
                results.append(result)
        else:
            # Concurrent execution with semaphore
            semaphore = asyncio.Semaphore(concurrency)

            async def run_with_semaphore(task: Task) -> RunResult:
                async with semaphore:
                    return await self.run_and_evaluate(task)

            results = await asyncio.gather(*[run_with_semaphore(t) for t in tasks])

        return list(results)
