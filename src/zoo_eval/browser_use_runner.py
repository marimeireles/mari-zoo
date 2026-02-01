"""browser_use harness implementation.

This module provides the BrowserUseRunner class for running tasks
using the browser_use library. It's one of several harness implementations.

For harness-agnostic code, see base_agent_runner.py and event_source.py.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any

from browser_use.agent.views import AgentSettings

from .base_agent_runner import BaseAgentRunner
from .models import AgentResult, RunConfig, Task, TaskAgentConfig, TaskResult, Universe
from .scenes import SceneManager
from .zoo import Zoo



def _create_step_hook(browser):
    """Create a step hook that captures page HTML after each agent step.

    Args:
        browser: browser_use Browser instance

    Returns:
        Tuple of (step_hook function, last_page_html dict for retrieving captured data)
    """
    last_page_html = {'html': None, 'url': None}

    async def step_hook(agent_instance):
        # Capture page HTML after each step
        try:
            cdp_session = await agent_instance.browser_session.get_or_create_cdp_session()

            # Get page HTML content via CDP
            doc = await cdp_session.cdp_client.send.DOM.getDocument(
                session_id=cdp_session.session_id
            )
            html_result = await cdp_session.cdp_client.send.DOM.getOuterHTML(
                params={'nodeId': doc['root']['nodeId']},
                session_id=cdp_session.session_id
            )
            last_page_html['html'] = html_result['outerHTML']

            # Also capture URL
            page = await browser.get_current_page()
            if page:
                last_page_html['url'] = page.url
        except Exception:
            pass  # Silently fail - we'll still have previous capture or None

    return step_hook, last_page_html


def _aggregate_agent_results(
    agent_results: list[AgentResult], task_id: int, autonomy_level: str
) -> TaskResult:
    """Aggregate multiple agent results into a single TaskResult."""
    combined_answer = "\n\n".join(
        f"[{r.agent_name}]: {r.answer}" for r in agent_results if r.answer
    )
    total_steps = sum(r.steps for r in agent_results)
    total_duration = sum(r.duration_seconds for r in agent_results)
    last_result = agent_results[-1] if agent_results else None

    return TaskResult(
        task_id=task_id,
        agent_results=list(agent_results),
        agent_answer=combined_answer if combined_answer else None,
        final_url=last_result.final_url if last_result else None,
        page_content=last_result.page_content if last_result else None,
        error=None,
        steps=total_steps,
        duration_seconds=total_duration,
        raw_result=last_result.raw_result if last_result else None,
        autonomy_level=autonomy_level,
    )


class BrowserUseRunner(BaseAgentRunner):
    """Runs tasks using browser-use. Supports single and multi-agent execution."""

    def __init__(
        self,
        zoo: Zoo,
        config: RunConfig | None = None,
        universe_path: Path | None = None,
        universe: Universe | None = None,
    ):
        super().__init__(zoo, config, universe_path, universe)
        self._llm_cache: dict[str, Any] = {}  # Cache LLMs by model name

    async def setup(self):
        """Initialize browser_use components."""
        os.environ["ANONYMIZED_TELEMETRY"] = "false"

    def _get_llm(self, agent_config: TaskAgentConfig):
        """Get or create LLM for an agent based on resolved model."""
        from .llm import create_chat_openai

        model = self._resolve_model(agent_config)

        # Cache LLMs to avoid recreating for same model
        if model not in self._llm_cache:
            self._llm_cache[model] = create_chat_openai(model)

        return self._llm_cache[model]

    async def teardown(self):
        """Clean up resources."""
        pass

    async def _create_browser(self):
        """Create a fresh browser instance for an agent."""
        from browser_use import Browser
        from browser_use.browser.profile import ProxySettings

        return Browser(
            headless=self.config.headless,
            proxy=ProxySettings(server=self.zoo.config.proxy_url),
            args=["--ignore-certificate-errors"],
        )

    async def _run_single_agent(
        self, agent_config: TaskAgentConfig, task: Task, start_url: str, autonomy_level: str = "L1",
        scene_manager: SceneManager | None = None
    ) -> AgentResult:
        """Run a single agent and return its result."""
        from browser_use import Agent

        start_time = time.time()
        browser = None

        try:
            browser = await self._create_browser()
            full_task = self._build_full_task(agent_config, task, start_url, autonomy_level)
            agent_context = self._build_agent_context(agent_config, task)

            agent = Agent(
                task=full_task,
                llm=self._get_llm(agent_config),
                browser=browser,
                extend_system_message=agent_context,
                settings=AgentSettings(use_judge=False),
            )

            step_hook, last_page_html = _create_step_hook(browser)

            try:
                result = await asyncio.wait_for(
                    agent.run(max_steps=self.config.max_steps, on_step_end=step_hook),
                    timeout=self.config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                return AgentResult(
                    agent_name=agent_config.name,
                    agent_role="",
                    success=False,
                    error=f"Timeout after {self.config.timeout_seconds}s",
                    duration_seconds=time.time() - start_time,
                )

            # Extract agent answer from result
            agent_answer = None
            if result and hasattr(result, "final_result"):
                fr = result.final_result()
                if fr:
                    agent_answer = (
                        fr.extracted_content if hasattr(fr, "extracted_content") else str(fr)
                    )

            return AgentResult(
                agent_name=agent_config.name,
                agent_role="",
                success=True,
                answer=agent_answer,
                final_url=last_page_html['url'],
                page_content=last_page_html['html'],
                error=None,
                steps=len(result.history) if result and hasattr(result, "history") else 0,
                duration_seconds=time.time() - start_time,
                raw_result=result,
            )

        except Exception as e:
            return AgentResult(
                agent_name=agent_config.name,
                agent_role="",
                success=False,
                error=str(e),
                duration_seconds=time.time() - start_time,
            )

        finally:
            if browser:
                try:
                    await browser.stop()
                except Exception:
                    pass

    async def _run_shared_browser_task(
        self, agents: list[TaskAgentConfig], task: Task, start_url: str, autonomy_level: str = "L1"
    ) -> TaskResult:
        """Run multi-agent task with shared browser and memory."""
        from browser_use import Agent

        overall_start = time.time()
        browser = None
        agent_results = []

        try:
            browser = await self._create_browser()

            # Run agents sequentially, sharing browser and memory
            for agent_config in agents:
                start_time = time.time()

                try:
                    full_task = self._build_full_task(agent_config, task, start_url, autonomy_level)
                    agent_context = self._build_agent_context(agent_config, task)

                    agent = Agent(
                        task=full_task,
                        llm=self._get_llm(agent_config),
                        browser=browser,
                        extend_system_message=agent_context,
                        settings=AgentSettings(use_judge=False),
                    )

                    step_hook, last_page_html = _create_step_hook(browser)

                    try:
                        result = await asyncio.wait_for(
                            agent.run(max_steps=self.config.max_steps, on_step_end=step_hook),
                            timeout=self.config.timeout_seconds,
                        )
                    except asyncio.TimeoutError:
                        agent_results.append(AgentResult(
                            agent_name=agent_config.name,
                            agent_role="",
                            success=False,
                            error=f"Timeout after {self.config.timeout_seconds}s",
                            duration_seconds=time.time() - start_time,
                        ))
                        continue

                    # Extract agent answer
                    agent_answer = None
                    if result and hasattr(result, "final_result"):
                        fr = result.final_result()
                        if fr:
                            agent_answer = (
                                fr.extracted_content if hasattr(fr, "extracted_content") else str(fr)
                            )

                    agent_results.append(AgentResult(
                        agent_name=agent_config.name,
                        agent_role="",
                        success=True,
                        answer=agent_answer,
                        final_url=last_page_html['url'],
                        page_content=last_page_html['html'],
                        error=None,
                        steps=len(result.history) if result and hasattr(result, "history") else 0,
                        duration_seconds=time.time() - start_time,
                        raw_result=result,
                    ))

                except Exception as e:
                    agent_results.append(AgentResult(
                        agent_name=agent_config.name,
                        agent_role="",
                        success=False,
                        error=str(e),
                        duration_seconds=time.time() - start_time,
                    ))

            # Use helper for aggregation, then fix duration
            task_result = _aggregate_agent_results(agent_results, task.task_id, autonomy_level)
            task_result.duration_seconds = time.time() - overall_start
            return task_result

        finally:
            if browser:
                try:
                    await browser.stop()
                except Exception:
                    pass

    async def run_tasks(
        self, tasks: list[Task]
    ) -> list[TaskResult]:
        """Run tasks with their defined agents."""
        # Note: Per-level reset happens automatically for tasks with scenes

        all_results = []

        for task in tasks:
            if not task.agents:
                print(f"Warning: Task {task.task_id} has no agents defined, skipping.")
                continue

            start_url = self.zoo.resolve_url(task.start_url)
            agents = list(task.agents.values())

            # Determine which autonomy levels to run for this task
            levels_to_run = []
            for autonomy_level in self.config.autonomy_levels:
                if (task.task_id, autonomy_level) in self.config.completed_pairs:
                    print(f"  Skipping task {task.task_id} {autonomy_level} (already completed)")
                    continue
                has_level = any(
                    autonomy_level in agent_config.autonomy_levels
                    for agent_config in agents
                )
                if has_level:
                    levels_to_run.append(autonomy_level)

            # Run each autonomy level with fresh state
            for level_idx, autonomy_level in enumerate(levels_to_run):
                # Auto-reset if task requires it or has a scene (scenes modify DB state)
                if (task.require_reset or task.scene_name) and self.universe:
                    sites_to_reset = task.sites if task.sites else self.universe.sites
                    self.zoo.reset_sites(sites_to_reset)

                task_start_time = time.time()

                # Set up scene manager for this autonomy level
                scene_manager = None
                if task.scene_name:
                    from .models import load_scene

                    scenes_dir = self.universe_path / "scenes" if self.universe_path else None
                    scene_path = scenes_dir / f"{task.scene_name}.yaml" if scenes_dir else None
                    scene = load_scene(scene_path) if scene_path and scene_path.exists() else None

                    use_proxy = self.config.use_proxy_events or (scene and scene.needs_proxy_events)
                    event_source = None
                    if use_proxy:
                        from .proxy_event_source import ProxyEventSource
                        session_id = str(uuid.uuid4())
                        event_source = ProxyEventSource(
                            redis_url=self.config.redis_url,
                            session_id=session_id,
                        )

                    universe_sites = self.universe.sites if self.universe else []
                    scene_manager = SceneManager(
                        self.zoo,
                        self.universe_path,
                        universe_sites,
                        event_source=event_source,
                    )
                    await scene_manager.load_and_setup(task.scene_name)
                    scene_manager.start_time = task_start_time
                    await scene_manager.setup_triggers()

                try:
                    if self.config.shared_browser:
                        result = await self._run_shared_browser_task(agents, task, start_url, autonomy_level)
                        all_results.append(result)
                    else:
                        async def run_agent(agent_config: TaskAgentConfig) -> AgentResult:
                            if scene_manager:
                                should_start = await scene_manager.wait_for_agent_start(agent_config.name)
                                if not should_start:
                                    return AgentResult(
                                        agent_name=agent_config.name,
                                        agent_role="",
                                        success=False,
                                        error=f"Start trigger timed out for agent {agent_config.name}",
                                        duration_seconds=0.0,
                                    )
                            return await self._run_single_agent(agent_config, task, start_url, autonomy_level, scene_manager)

                        agent_results = await asyncio.gather(*[run_agent(a) for a in agents])
                        task_result = _aggregate_agent_results(list(agent_results), task.task_id, autonomy_level)
                        all_results.append(task_result)
                finally:
                    if scene_manager:
                        try:
                            await scene_manager.cleanup()
                        except Exception:
                            pass

        return all_results
