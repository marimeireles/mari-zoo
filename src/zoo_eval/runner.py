"""Task runner that orchestrates browser_use agent execution."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .evaluators import EvalResult, evaluate_task
from .models import Task, TaskResult
from .zoo import Zoo


@dataclass
class RunConfig:
    """Configuration for task runs."""

    max_steps: int = 50
    timeout_seconds: float = 300.0
    headless: bool = True
    save_traces: bool = False
    trace_dir: str = "./traces"


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
        self._agent = None
        self._browser = None

    async def setup(self):
        """Initialize browser_use components."""
        # Lazy import to avoid loading at module level
        from browser_use import Agent, Browser, BrowserConfig
        from langchain_anthropic import ChatAnthropic

        browser_config = BrowserConfig(
            headless=self.config.headless,
            proxy={"server": self.zoo.config.proxy_url},
            extra_chromium_args=["--ignore-certificate-errors"],
        )
        self._browser = Browser(config=browser_config)

        # Use Anthropic Claude as the LLM
        self._llm = ChatAnthropic(model="claude-sonnet-4-20250514")

    async def teardown(self):
        """Clean up resources."""
        if self._browser:
            await self._browser.close()
            self._browser = None

    async def run_task(self, task: Task) -> TaskResult:
        """Run a single task and return the result."""
        from browser_use import Agent

        start_time = time.time()
        start_url = self.zoo.resolve_url(task.start_url)

        try:
            # Reset if required
            if task.require_reset:
                self.zoo.reset_databases()

            # Create agent for this task
            agent = Agent(
                task=task.intent,
                llm=self._llm,
                browser=self._browser,
            )

            # Navigate to start URL first
            browser_context = await self._browser.new_context()
            page = await browser_context.new_page()
            await page.goto(start_url)

            # Run the agent
            result = await agent.run(max_steps=self.config.max_steps)

            # Extract results
            final_url = page.url if page else None
            page_content = await page.content() if page else None

            # Get the agent's answer from the result
            agent_answer = None
            if result and hasattr(result, 'final_result'):
                agent_answer = result.final_result

            await browser_context.close()

            return TaskResult(
                task_id=task.task_id,
                success=True,
                agent_answer=agent_answer,
                final_url=final_url,
                page_content=page_content,
                steps=len(result.history) if result and hasattr(result, 'history') else 0,
                duration_seconds=time.time() - start_time,
            )

        except Exception as e:
            return TaskResult(
                task_id=task.task_id,
                success=False,
                error=str(e),
                duration_seconds=time.time() - start_time,
            )

    async def run_and_evaluate(self, task: Task) -> RunResult:
        """Run a task and evaluate the result."""
        task_result = await self.run_task(task)
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
