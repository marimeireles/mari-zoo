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
                f"Go to {start_url}. {login_hint}{agent_config.goal}"
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

    async def _run_shared_browser_task(
        self, agents: list[AgentConfig], task: Task, start_url: str
    ) -> TaskResult:
        """Run multi-agent task with shared browser and memory."""
        from browser_use import Agent

        overall_start = time.time()
        browser = None
        agent_results = []

        try:
            # Create single shared browser
            browser = await self._create_browser()

            # Run agents sequentially, sharing browser and memory
            for agent_config in agents:
                start_time = time.time()

                try:
                    # Build agent-specific task
                    login_hint = get_login_hint(task.sites) if task.require_login else ""
                    full_task = (
                        f"You are {agent_config.name}, {agent_config.persona}. "
                        f"Go to {start_url}. {login_hint}{agent_config.goal}"
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

    def _assign_tasks_to_agents(
        self, agents: list[AgentConfig], tasks: list[Task]
    ) -> dict[str, list[Task]]:
        """Assign tasks to agents sequentially. Extra tasks go to last agent."""
        assignment = {agent.name: [] for agent in agents}

        if not tasks:
            return assignment

        # Assign tasks to agents sequentially
        for i, task in enumerate(tasks):
            if i < len(agents):
                assignment[agents[i].name].append(task)
            else:
                # Overflow: assign to last agent
                assignment[agents[-1].name].append(task)

        # Warn if overflow
        overflow_count = len(tasks) - len(agents)
        if overflow_count > 0:
            import sys

            print(
                f"Warning: {overflow_count} extra task(s) assigned to last agent ({agents[-1].name}). "
                "This is normal for --shared-browser mode.",
                file=sys.stderr,
            )

        return assignment

    async def run_multi_agent_tasks(
        self, agents: list[AgentConfig], tasks: list[Task]
    ) -> list[TaskResult]:
        """Run multiple tasks distributed across agents."""
        # Restart Zoo for clean state
        self.zoo.restart()
        # Wait for Zoo to be ready
        for _ in range(10):
            if self.zoo.is_running():
                break
            time.sleep(1)

        # Assign tasks to agents
        assignment = self._assign_tasks_to_agents(agents, tasks)

        # Reset if any task requires it
        if any(t.require_reset for t in tasks):
            self.zoo.reset_databases()

        all_results = []

        if self.config.shared_browser:
            # Shared browser: run agents sequentially
            for agent in agents:
                agent_tasks = assignment[agent.name]
                if not agent_tasks:
                    continue  # Skip idle agents

                for task in agent_tasks:
                    start_url = self.zoo.resolve_url(task.start_url)
                    result = await self._run_shared_browser_task([agent], task, start_url)
                    all_results.append(result)
        else:
            # Separate browsers: run all agents concurrently
            async def run_agent_tasks(agent: AgentConfig) -> list[TaskResult]:
                """Run all tasks assigned to this agent."""
                agent_tasks = assignment[agent.name]
                results = []

                for task in agent_tasks:
                    start_url = self.zoo.resolve_url(task.start_url)
                    agent_result = await self._run_single_agent(agent, task, start_url)

                    # Convert AgentResult to TaskResult
                    task_result = TaskResult(
                        task_id=task.task_id,
                        success=agent_result.success,
                        agent_results=[agent_result],
                        agent_answer=agent_result.answer,
                        final_url=agent_result.final_url,
                        page_content=agent_result.page_content,
                        error=agent_result.error,
                        steps=agent_result.steps,
                        duration_seconds=agent_result.duration_seconds,
                    )
                    results.append(task_result)

                return results

            # Run all agents concurrently
            agent_results_lists = await asyncio.gather(
                *[run_agent_tasks(agent) for agent in agents]
            )

            # Flatten results
            for results_list in agent_results_lists:
                all_results.extend(results_list)

        return all_results
