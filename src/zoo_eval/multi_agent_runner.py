"""Multi-agent task runner for concurrent agent execution."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from .auth import get_login_hint
from .models import AgentConfig, AgentResult, RunConfig, Task, TaskResult
from .zoo import Zoo


class MultiAgentRunner:
    """Runs tasks with multiple concurrent agents."""

    def __init__(self, zoo: Zoo, config: RunConfig | None = None):
        self.zoo = zoo
        self.config = config or RunConfig()
        self._llm = None

    async def setup(self):
        """Initialize browser_use components."""
        os.environ["ANONYMIZED_TELEMETRY"] = "false"
        self._llm = self._create_llm()

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
        self, agent_config: AgentConfig, task: Task, start_url: str
    ) -> AgentResult:
        """Run a single agent and return its result."""
        from browser_use import Agent

        start_time = time.time()
        browser = None

        try:
            # Create fresh browser for this agent
            browser = await self._create_browser()

            # Build agent-specific task
            login_hint = get_login_hint(task.sites) if task.require_login else ""
            full_task = (
                f"You are {agent_config.name}, {agent_config.persona}. "
                f"Go to {start_url}. {login_hint}{agent_config.initial_task}"
            )

            # Create agent
            agent = Agent(
                task=full_task,
                llm=self._llm,
                browser=browser,
            )

            # Run the agent with timeout
            try:
                result = await asyncio.wait_for(
                    agent.run(max_steps=self.config.max_steps),
                    timeout=self.config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                return AgentResult(
                    agent_name=agent_config.name,
                    agent_role=agent_config.role,
                    success=False,
                    error=f"Timeout after {self.config.timeout_seconds}s",
                    duration_seconds=time.time() - start_time,
                )

            # Extract results from agent
            agent_answer = None
            final_url = None
            page_content = None

            if result:
                # Get the agent's final result
                if hasattr(result, "final_result"):
                    fr = result.final_result()
                    if fr:
                        agent_answer = (
                            fr.extracted_content
                            if hasattr(fr, "extracted_content")
                            else str(fr)
                        )

                # Try to get current page info
                try:
                    final_url = await browser.get_current_page_url()
                    page = await browser.get_current_page()
                    if page:
                        page_content = await page.content()
                except Exception:
                    pass

            return AgentResult(
                agent_name=agent_config.name,
                agent_role=agent_config.role,
                success=True,
                answer=agent_answer,
                final_url=final_url,
                page_content=page_content,
                steps=len(result.history) if result and hasattr(result, "history") else 0,
                duration_seconds=time.time() - start_time,
            )

        except Exception as e:
            return AgentResult(
                agent_name=agent_config.name,
                agent_role=agent_config.role,
                success=False,
                error=str(e),
                duration_seconds=time.time() - start_time,
            )

        finally:
            # Always clean up the browser
            if browser:
                try:
                    await browser.stop()
                except Exception:
                    pass

    async def _run_shared_browser_task(self, task: Task, start_url: str) -> TaskResult:
        """Run multi-agent task with shared browser and memory."""
        from browser_use import Agent

        overall_start = time.time()
        browser = None
        agent_results = []

        try:
            # Create single shared browser
            browser = await self._create_browser()

            # Run agents sequentially, sharing browser and memory
            for agent_config in task.agents:
                start_time = time.time()

                try:
                    # Build agent-specific task
                    login_hint = get_login_hint(task.sites) if task.require_login else ""
                    full_task = (
                        f"You are {agent_config.name}, {agent_config.persona}. "
                        f"Go to {start_url}. {login_hint}{agent_config.initial_task}"
                    )

                    # Create agent with shared browser
                    agent = Agent(
                        task=full_task,
                        llm=self._llm,
                        browser=browser,
                    )

                    # Run the agent
                    try:
                        result = await asyncio.wait_for(
                            agent.run(max_steps=self.config.max_steps),
                            timeout=self.config.timeout_seconds,
                        )
                    except asyncio.TimeoutError:
                        agent_results.append(
                            AgentResult(
                                agent_name=agent_config.name,
                                agent_role=agent_config.role,
                                success=False,
                                error=f"Timeout after {self.config.timeout_seconds}s",
                                duration_seconds=time.time() - start_time,
                            )
                        )
                        continue

                    # Extract results
                    agent_answer = None
                    final_url = None
                    page_content = None

                    if result:
                        if hasattr(result, "final_result"):
                            fr = result.final_result()
                            if fr:
                                agent_answer = (
                                    fr.extracted_content
                                    if hasattr(fr, "extracted_content")
                                    else str(fr)
                                )

                        try:
                            final_url = await browser.get_current_page_url()
                            page = await browser.get_current_page()
                            if page:
                                page_content = await page.content()
                        except Exception:
                            pass

                    agent_results.append(
                        AgentResult(
                            agent_name=agent_config.name,
                            agent_role=agent_config.role,
                            success=True,
                            answer=agent_answer,
                            final_url=final_url,
                            page_content=page_content,
                            steps=len(result.history) if result and hasattr(result, "history") else 0,
                            duration_seconds=time.time() - start_time,
                        )
                    )

                except Exception as e:
                    agent_results.append(
                        AgentResult(
                            agent_name=agent_config.name,
                            agent_role=agent_config.role,
                            success=False,
                            error=str(e),
                            duration_seconds=time.time() - start_time,
                        )
                    )

            # Aggregate results
            all_succeeded = all(r.success for r in agent_results)
            combined_answer = "\n\n".join(
                f"[{r.agent_name}]: {r.answer}" for r in agent_results if r.answer
            )
            total_steps = sum(r.steps for r in agent_results)

            return TaskResult(
                task_id=task.task_id,
                success=all_succeeded,
                agent_results=agent_results,
                agent_answer=combined_answer if combined_answer else None,
                steps=total_steps,
                duration_seconds=time.time() - overall_start,
            )

        finally:
            # Clean up shared browser
            if browser:
                try:
                    await browser.stop()
                except Exception:
                    pass

    async def run_multi_agent_task(self, task: Task) -> TaskResult:
        """Run a multi-agent task - either concurrent (separate browsers) or sequential (shared browser)."""
        # Restart Zoo for clean state
        self.zoo.restart()
        # Wait for Zoo to be ready
        for _ in range(10):
            if self.zoo.is_running():
                break
            time.sleep(1)

        overall_start = time.time()
        start_url = self.zoo.resolve_url(task.start_url)

        try:
            # Reset if required
            if task.require_reset:
                self.zoo.reset_databases()

            # Route to appropriate execution mode
            if self.config.shared_browser:
                return await self._run_shared_browser_task(task, start_url)

            # Default: Run all agents concurrently with separate browsers
            agent_tasks = [
                self._run_single_agent(agent_config, task, start_url)
                for agent_config in task.agents
            ]
            agent_results = await asyncio.gather(*agent_tasks)

            # Aggregate results
            all_succeeded = all(r.success for r in agent_results)
            combined_answer = "\n\n".join(
                f"[{r.agent_name}]: {r.answer}" for r in agent_results if r.answer
            )
            total_steps = sum(r.steps for r in agent_results)

            return TaskResult(
                task_id=task.task_id,
                success=all_succeeded,
                agent_results=list(agent_results),
                agent_answer=combined_answer if combined_answer else None,
                steps=total_steps,
                duration_seconds=time.time() - overall_start,
            )

        except Exception as e:
            return TaskResult(
                task_id=task.task_id,
                success=False,
                error=str(e),
                duration_seconds=time.time() - overall_start,
            )
