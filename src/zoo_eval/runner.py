"""Task runner that orchestrates browser_use agent execution."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .auth import get_login_hint
from .evaluators import EvalResult, evaluate_task
from .models import Task, TaskResult
from .zoo import Zoo


@dataclass
class RunConfig:
    """Configuration for task runs."""

    max_steps: int = 50
    timeout_seconds: float = 300.0
    headless: bool = True
    save_traces: bool = True
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
        from browser_use import Agent, Browser, ChatOpenAI
        from browser_use.browser.profile import ProxySettings

        self._browser = Browser(
            headless=self.config.headless,
            proxy=ProxySettings(server=self.zoo.config.proxy_url),
            args=["--ignore-certificate-errors"],
        )

        # Use OpenAI GPT-4o as the LLM
        self._llm = ChatOpenAI(model="gpt-4o")

    async def teardown(self):
        """Clean up resources."""
        if self._browser:
            await self._browser.stop()
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

            # Build task with login hint if needed
            login_hint = get_login_hint(task.sites) if task.require_login else ""
            full_task = f"Go to {start_url}. {login_hint}{task.intent}"

            # Create agent for this task
            agent = Agent(
                task=full_task,
                llm=self._llm,
                browser=self._browser,
            )

            # Run the agent
            result = await agent.run(max_steps=self.config.max_steps)

            # Save trace if configured
            if self.config.save_traces:
                from pathlib import Path
                trace_dir = Path(self.config.trace_dir)
                trace_dir.mkdir(parents=True, exist_ok=True)
                trace_path = trace_dir / f"task_{task.task_id}.json"
                try:
                    agent.save_history(trace_path)
                except Exception as e:
                    pass  # Don't fail the task if trace saving fails

            # Extract results from agent
            agent_answer = None
            final_url = None
            page_content = None

            if result:
                # Get the agent's final result (it's a method, not a property)
                if hasattr(result, 'final_result'):
                    fr = result.final_result()
                    if fr:
                        agent_answer = fr.extracted_content if hasattr(fr, 'extracted_content') else str(fr)

                # Try to get current page info
                try:
                    final_url = await self._browser.get_current_page_url()
                    page = await self._browser.get_current_page()
                    if page:
                        page_content = await page.content()
                except Exception:
                    pass

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
