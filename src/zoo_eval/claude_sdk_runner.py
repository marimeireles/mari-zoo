"""Claude Agent SDK based runner with playwright-mcp."""

from __future__ import annotations

import asyncio
import gc
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from .base_agent_runner import BaseAgentRunner
from .models import AgentResult, RunConfig, Task, TaskAgentConfig, TaskResult, Universe
from .scenes import SceneManager
from .zoo import Zoo

# Delay between sequential agent runs to allow SDK async cleanup
INTER_AGENT_DELAY_SECONDS = 5


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
            # Build the prompt using shared method
            prompt = self._build_full_task(agent_config, task, start_url, autonomy_level)
            prompt += (
                "\n\nUse the browser tools to complete this task. "
                "When done, use browser_snapshot to capture the final page state, "
                "then provide your final answer."
            )

            # Configure the agent
            options = ClaudeAgentOptions(
                mcp_servers=self._mcp_config,
                allowed_tools=["mcp__zoo-playwright__*"],
                model=self.config.claude_model,
                max_turns=self.config.max_steps,
                # Log SDK stderr for debugging
                stderr=lambda msg: print(f"      [sdk] {msg}") if msg.strip() else None,
            )

            # Run the agent with proper timeout enforcement
            final_answer = None
            result_message: ResultMessage | None = None
            last_text_block = None  # Fallback for answer if no ResultMessage

            try:
                print(f"    Agent {agent_config.name}: Starting task...")
                async with asyncio.timeout(self.config.timeout_seconds):
                    # Create generator and ensure proper cleanup
                    gen = query(prompt=prompt, options=options)
                    try:
                        last_tool_name = None
                        async for message in gen:
                            if isinstance(message, AssistantMessage):
                                messages_log.append(message)
                                for block in message.content:
                                    if isinstance(block, TextBlock):
                                        # Show agent's reasoning (truncated)
                                        text = block.text[:200] + "..." if len(block.text) > 200 else block.text
                                        print(f"    💭 {text}")
                                        # Keep track of last text for answer fallback
                                        last_text_block = block.text
                                    elif isinstance(block, ToolUseBlock):
                                        steps += 1
                                        last_tool_name = block.name
                                        tool_name = block.name.replace("mcp__zoo-playwright__", "")
                                        print(f"    [{steps}] {tool_name}")
                                        # Track URL from navigate calls
                                        if block.name == "mcp__zoo-playwright__browser_navigate":
                                            if hasattr(block, "input") and block.input:
                                                final_url = block.input.get("url")
                                                print(f"        → {final_url}")

                            elif isinstance(message, UserMessage):
                                # Capture tool results (especially browser_snapshot)
                                for block in message.content:
                                    if isinstance(block, ToolResultBlock):
                                        content = block.content if hasattr(block, "content") else ""
                                        # Capture page content from snapshot
                                        if last_tool_name and "snapshot" in last_tool_name:
                                            page_content = content
                                        # Also capture from any tool result as fallback
                                        elif content and len(content) > 100:
                                            page_content = content

                            elif isinstance(message, ResultMessage):
                                result_message = message
                                final_answer = message.result
                                print(f"    Agent {agent_config.name}: Done ({steps} steps)")
                                break
                    finally:
                        # Explicitly close generator to avoid cancel scope issues
                        await gen.aclose()

            except asyncio.TimeoutError:
                return AgentResult(
                    agent_name=agent_config.name,
                    agent_role=self._get_agent_role(agent_config),
                    success=False,
                    error=f"Timeout after {self.config.timeout_seconds}s",
                    steps=steps,
                    duration_seconds=time.time() - start_time,
                )

            # Note: Page content capture via separate query causes SDK issues
            # For PROGRAM_HTML evaluation, rely on the agent's final answer instead

            # Use last text block as fallback if no explicit ResultMessage
            effective_answer = final_answer or last_text_block

            return AgentResult(
                agent_name=agent_config.name,
                agent_role=self._get_agent_role(agent_config),
                success=result_message is not None and not result_message.is_error,
                answer=effective_answer,
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

    async def run_multi_agent_tasks(self, tasks: list[Task]) -> list[TaskResult]:
        """Run tasks with their defined agents."""
        # Collect all sites needed by tasks
        services = []
        if self.universe:
            all_sites = set()
            for task in tasks:
                all_sites.update(task.sites)
            services = self.universe.get_services_for_sites(list(all_sites))

        if not self.config.skip_zoo_reset:
            # Restart only needed services in correct order
            self.zoo.restart(services if services else None)

            # Wait for services to be healthy
            if services:
                self.zoo.wait_for_services(services, timeout=120, verbose=True)

            # Reset if any task requires it
            if any(t.require_reset for t in tasks):
                self.zoo.reset_databases()

        all_results = []

        for task in tasks:
            if not task.agents:
                print(f"Warning: Task {task.task_id} has no agents defined, skipping.")
                continue

            start_url = self.zoo.resolve_url(task.start_url)
            task_start_time = time.time()

            # Activate scene once per task
            scene_manager = None
            if task.scene_name:
                scene_manager = SceneManager(self.zoo, self.universe_path)
                await scene_manager.load_and_activate_scene(task.scene_name, task_start_time)

            try:
                agents = list(task.agents.values())

                # Run each task with configured autonomy levels
                for autonomy_level in self.config.autonomy_levels:
                    # Skip if this (task_id, level) was already completed (for resume)
                    if (task.task_id, autonomy_level) in self.config.completed_pairs:
                        print(f"  Skipping task {task.task_id} {autonomy_level} (already completed)")
                        continue

                    # Run agents sequentially (Claude SDK shares MCP server state)
                    agent_results = []
                    for i, agent_config in enumerate(agents):
                        # Force cleanup between queries - SDK has async context issues
                        gc.collect()
                        if i > 0:
                            # Wait between agents for SDK cleanup
                            await asyncio.sleep(INTER_AGENT_DELAY_SECONDS)
                        # Run each agent in isolated task to prevent cancel scope leakage
                        result = await asyncio.create_task(
                            self._run_single_agent(
                                agent_config, task, start_url, autonomy_level
                            )
                        )
                        agent_results.append(result)

                    # Aggregate results
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
                # Clean up scene manager after all autonomy levels are done
                if scene_manager:
                    try:
                        await scene_manager.cleanup()
                    except Exception as e:
                        print(f"  Warning: Scene cleanup failed: {e}")

        return all_results
