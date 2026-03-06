"""Claude Agent SDK based runner with playwright-mcp."""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    ToolUseBlock,
    query,
)

from .base_agent_runner import BaseAgentRunner
from .models import AgentResult, RunConfig, Task, TaskAgentConfig, TaskResult, Universe
from .scenes import SceneManager
from .zoo import Zoo


class ClaudeSDKRunner(BaseAgentRunner):
    """Runs tasks using Claude Agent SDK with playwright-mcp."""

    def __init__(
        self,
        zoo: Zoo,
        config: RunConfig | None = None,
        universe_path: Path | None = None,
        universe: Universe | None = None,
    ):
        super().__init__(zoo, config, universe_path, universe)
        self._mcp_config: dict[str, Any] | None = None

    async def setup(self) -> None:
        """Configure MCP server settings."""
        # Build playwright-mcp config for the Zoo environment
        browser_args = [
            "@playwright/mcp@latest",
            "--browser",
            "firefox",
        ]

        # Add proxy if configured (required for .zoo domain resolution)
        if self.zoo.config.proxy_url:
            browser_args.extend(["--proxy-server", self.zoo.config.proxy_url])

        # Handle self-signed certs in Zoo
        browser_args.append("--ignore-https-errors")

        # Add headless mode if configured
        if self.config.headless:
            browser_args.append("--headless")

        self._mcp_config = {
            "zoo-playwright": {
                "command": "npx",
                "args": browser_args,
            }
        }

    async def teardown(self) -> None:
        """Clean up - SDK handles MCP server lifecycle automatically."""
        pass

    def _get_agent_role(self, agent_config: TaskAgentConfig) -> str:
        """Get the role for an agent from universe config."""
        universe_agent = self._get_universe_agent(agent_config.name)
        return universe_agent.role if universe_agent else ""

    async def _run_single_agent(
        self,
        agent_config: TaskAgentConfig,
        task: Task,
        start_url: str,
        autonomy_level: str = "L1",
    ) -> AgentResult:
        """Run a single agent using Claude Agent SDK."""
        start_time = time.time()
        steps = 0
        final_url = None
        page_content = None
        messages_log: list[Any] = []

        try:
            # Build the prompt using shared methods
            agent_context = self._build_agent_context(agent_config, task)
            task_prompt = self._build_full_task(agent_config, task, start_url, autonomy_level)
            prompt = f"{agent_context}\n\n{task_prompt}"
            prompt += (
                "\n\nUse the browser tools to complete this task. "
                "When done, provide your final answer."
            )

            # Configure the agent
            options = ClaudeAgentOptions(
                mcp_servers=self._mcp_config,
                allowed_tools=["mcp__zoo-playwright__*"],
                model=self.config.claude_model,
                max_turns=self.config.max_steps,
            )

            # Run the agent with proper timeout enforcement
            final_answer = None
            result_message: ResultMessage | None = None

            try:
                async with asyncio.timeout(self.config.timeout_seconds):
                    async for message in query(prompt=prompt, options=options):
                        if isinstance(message, AssistantMessage):
                            messages_log.append(message)
                            for block in message.content:
                                if isinstance(block, ToolUseBlock):
                                    steps += 1
                                    # Track URL from navigate calls
                                    if block.name == "mcp__zoo-playwright__browser_navigate":
                                        if hasattr(block, "input") and block.input:
                                            final_url = block.input.get("url")

                        elif isinstance(message, ResultMessage):
                            result_message = message
                            final_answer = message.result
                            break

            except asyncio.TimeoutError:
                return AgentResult(
                    agent_name=agent_config.name,
                    agent_role=self._get_agent_role(agent_config),
                    success=False,
                    error=f"Timeout after {self.config.timeout_seconds}s",
                    steps=steps,
                    duration_seconds=time.time() - start_time,
                )

            # Capture final page content for PROGRAM_HTML evaluation
            if steps > 0 and page_content is None:
                page_content = await self._capture_page_content(options)

            return AgentResult(
                agent_name=agent_config.name,
                agent_role=self._get_agent_role(agent_config),
                success=result_message is not None and not result_message.is_error,
                answer=final_answer,
                final_url=final_url,
                page_content=page_content,
                steps=steps,
                duration_seconds=time.time() - start_time,
                raw_result={
                    "messages": messages_log,
                    "result_message": result_message,
                    "cost_usd": result_message.total_cost_usd if result_message else None,
                },
            )

        except Exception as e:
            return AgentResult(
                agent_name=agent_config.name,
                agent_role=self._get_agent_role(agent_config),
                success=False,
                error=str(e),
                steps=steps,
                duration_seconds=time.time() - start_time,
            )

    async def _capture_page_content(self, options: ClaudeAgentOptions) -> str | None:
        """Capture current page content via browser_snapshot for evaluation."""
        try:
            async with asyncio.timeout(30):  # Short timeout for snapshot
                async for message in query(
                    prompt="Use browser_snapshot to capture the current page state. Return only the snapshot.",
                    options=options,
                ):
                    if isinstance(message, ResultMessage):
                        return message.result
        except (asyncio.TimeoutError, Exception):
            pass
        return None

    async def run_tasks(self, tasks: list[Task]) -> list[TaskResult]:
        """Run tasks with their defined agents."""
        # Collect all sites needed by tasks
        services = []
        if self.universe:
            all_sites = set()
            for task in tasks:
                all_sites.update(task.sites)
            services = self.universe.get_services_for_sites(list(all_sites))

        # Restart only needed services in correct order
        self.zoo.restart(services if services else None)

        # Wait for services to be healthy
        if services:
            self.zoo.wait_for_services(services, timeout=120, verbose=True)

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
                    self.zoo.reset_sites_fast(sites_to_reset)

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
                    async def run_agent(agent_config: TaskAgentConfig) -> AgentResult:
                        if scene_manager:
                            should_start = await scene_manager.wait_for_agent_start(agent_config.name)
                            if not should_start:
                                return AgentResult(
                                    agent_name=agent_config.name,
                                    agent_role=self._get_agent_role(agent_config),
                                    success=False,
                                    error=f"Start trigger timed out for agent {agent_config.name}",
                                    duration_seconds=0.0,
                                )
                        return await self._run_single_agent(agent_config, task, start_url, autonomy_level)

                    agent_results = await asyncio.gather(*[run_agent(a) for a in agents])

                    all_succeeded = all(r.success for r in agent_results)
                    combined_answer = "\n\n".join(
                        f"[{r.agent_name}]: {r.answer}" for r in agent_results if r.answer
                    )
                    total_steps = sum(r.steps for r in agent_results)
                    total_duration = sum(r.duration_seconds for r in agent_results)
                    last_result = agent_results[-1] if agent_results else None

                    task_result = TaskResult(
                        task_id=task.task_id,
                        success=all_succeeded,
                        agent_results=agent_results,
                        agent_answer=combined_answer if combined_answer else None,
                        final_url=last_result.final_url if last_result else None,
                        page_content=last_result.page_content if last_result else None,
                        steps=total_steps,
                        duration_seconds=total_duration,
                        raw_result=last_result.raw_result if last_result else None,
                        autonomy_level=autonomy_level,
                        scene_manager=scene_manager,
                        scene_name=task.scene_name,
                    )
                    all_results.append(task_result)

                finally:
                    if scene_manager:
                        try:
                            await scene_manager.cleanup()
                        except Exception:
                            pass

        return all_results
