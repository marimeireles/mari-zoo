"""Multi-agent task runner for concurrent agent execution."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from .auth import get_login_hint
from .models import AgentConfig, AgentResult, RunConfig, Task, TaskResult
from .scenes import SceneManager
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
        # TODO add options to deal with LLM providers other than OpenAIs
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
        self, agent_config: AgentConfig, task: Task, start_url: str, autonomy_level: str = "L1"
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
            # Use autonomy level if available, otherwise fall back to intent
            task_instruction = task.autonomy_levels.get(autonomy_level, task.intent) if task.autonomy_levels else task.intent
            full_task = (
                f"You are {agent_config.name}, {agent_config.persona}. "
                f"Go to {start_url}. {login_hint}{task_instruction}"
            )

            # Create agent
            agent = Agent(
                task=full_task,
                llm=self._llm,
                browser=browser,
            )

            # Closure to capture page HTML at each step
            last_page_html = {'html': None, 'url': None}

            async def step_hook(agent_instance):
                """Capture page HTML after each step."""
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
                except Exception as e:
                    # Silently fail - we'll still have previous capture or None
                    pass

            # Run the agent with timeout and step hook
            try:
                result = await asyncio.wait_for(
                    agent.run(max_steps=self.config.max_steps, on_step_end=step_hook),
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

            # Use captured page content from step hook
            final_url = last_page_html['url']
            page_content = last_page_html['html']

            # Extract results from agent
            agent_answer = None
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


            return AgentResult(
                agent_name=agent_config.name,
                agent_role=agent_config.role,
                success=True,
                answer=agent_answer,
                final_url=final_url,
                page_content=page_content,
                steps=len(result.history) if result and hasattr(result, "history") else 0,
                duration_seconds=time.time() - start_time,
                raw_result=result,  # Store raw result from agent.run()
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
            # NOW close browser after we've captured everything
            if browser:
                try:
                    await browser.stop()
                except Exception:
                    pass

    async def _run_shared_browser_task(
        self, agents: list[AgentConfig], task: Task, start_url: str, autonomy_level: str = "L1"
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
                    # Use autonomy level if available, otherwise fall back to intent
                    task_instruction = task.autonomy_levels.get(autonomy_level, task.intent) if task.autonomy_levels else task.intent
                    full_task = (
                        f"You are {agent_config.name}, {agent_config.persona}. "
                        f"Go to {start_url}. {login_hint}{task_instruction}"
                    )

                    # Create agent with shared browser
                    agent = Agent(
                        task=full_task,
                        llm=self._llm,
                        browser=browser,
                    )

                    # Closure to capture page HTML at each step
                    last_page_html = {'html': None, 'url': None}

                    async def step_hook(agent_instance):
                        """Capture page HTML after each step."""
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
                        except Exception as e:
                            # Silently fail - we'll still have previous capture or None
                            pass

                    # Run the agent with step hook
                    try:
                        result = await asyncio.wait_for(
                            agent.run(max_steps=self.config.max_steps, on_step_end=step_hook),
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

                    # Use captured page content from step hook
                    final_url = last_page_html['url']
                    page_content = last_page_html['html']

                    # Extract results
                    agent_answer = None
                    if result:
                        if hasattr(result, "final_result"):
                            fr = result.final_result()
                            if fr:
                                agent_answer = (
                                    fr.extracted_content
                                    if hasattr(fr, "extracted_content")
                                    else str(fr)
                                )


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
                            raw_result=result,  # Store raw result from agent.run()
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
            # Use the last agent's raw_result for the TaskResult
            last_raw_result = agent_results[-1].raw_result if agent_results else None

            return TaskResult(
                task_id=task.task_id,
                success=all_succeeded,
                agent_results=agent_results,
                agent_answer=combined_answer if combined_answer else None,
                steps=total_steps,
                duration_seconds=time.time() - overall_start,
                raw_result=last_raw_result,  # Include raw result from last agent
                autonomy_level=autonomy_level,  # Track which level was used
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
                    task_start_time = time.time()

                    # Activate scene once per task (before autonomy level loop)
                    scene_manager = None
                    if task.scene_name:
                        scene_manager = SceneManager(self.zoo)
                        await scene_manager.load_and_activate_scene(task.scene_name, task_start_time)

                    try:
                        # Run each task with all autonomy levels
                        for autonomy_level in ["L0", "L1", "L2"]:
                            result = await self._run_shared_browser_task([agent], task, start_url, autonomy_level)
                            all_results.append(result)
                    finally:
                        # Clean up scene manager after all autonomy levels are done
                        if scene_manager:
                            try:
                                await scene_manager.cleanup()
                            except Exception:
                                pass
        else:
            # Separate browsers: run all agents concurrently
            async def run_agent_tasks(agent: AgentConfig) -> list[TaskResult]:
                """Run all tasks assigned to this agent."""
                agent_tasks = assignment[agent.name]
                results = []

                for task in agent_tasks:
                    start_url = self.zoo.resolve_url(task.start_url)
                    task_start_time = time.time()

                    # Activate scene once per task (before autonomy level loop)
                    scene_manager = None
                    if task.scene_name:
                        scene_manager = SceneManager(self.zoo)
                        await scene_manager.load_and_activate_scene(task.scene_name, task_start_time)

                    try:
                        # Run each task with all autonomy levels
                        for autonomy_level in ["L0", "L1", "L2"]:
                            agent_result = await self._run_single_agent(agent, task, start_url, autonomy_level)

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
                                raw_result=agent_result.raw_result,  # Pass through raw result
                                autonomy_level=autonomy_level,  # Track which level was used
                            )
                            results.append(task_result)
                    finally:
                        # Clean up scene manager after all autonomy levels are done
                        if scene_manager:
                            try:
                                await scene_manager.cleanup()
                            except Exception:
                                pass

                return results

            # Run all agents concurrently
            agent_results_lists = await asyncio.gather(
                *[run_agent_tasks(agent) for agent in agents]
            )

            # Flatten results
            for results_list in agent_results_lists:
                all_results.extend(results_list)

        return all_results
