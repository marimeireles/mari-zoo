"""Multi-agent task runner for concurrent agent execution."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from .models import AgentResult, RunConfig, Task, TaskAgentConfig, TaskResult, Universe
from .scenes import SceneManager
from .zoo import Zoo


class MultiAgentRunner:
    """Runs tasks with multiple concurrent agents."""

    def __init__(self, zoo: Zoo, config: RunConfig | None = None, universe_path: Path | None = None, universe: Universe | None = None):
        self.zoo = zoo
        self.config = config or RunConfig()
        self.universe_path = universe_path
        self.universe = universe
        self._llm = None

    async def setup(self):
        """Initialize browser_use components."""
        os.environ["ANONYMIZED_TELEMETRY"] = "false"
        self._llm = self._create_llm()

    def _get_universe_agent(self, agent_name: str):
        """Get the universe agent config by name."""
        if not self.universe:
            return None
        for agent in self.universe.agents:
            if agent.name == agent_name:
                return agent
        return None

    def _build_agent_context(self, agent_config: TaskAgentConfig) -> str:
        """Build the agent context string from universe config."""
        universe_agent = self._get_universe_agent(agent_config.name)

        # Start with name
        context = f"You are {agent_config.name}"

        # Add role if available
        if universe_agent and universe_agent.role:
            context += f", a {universe_agent.role}"
        context += "."

        # Add persona if available
        if universe_agent and universe_agent.persona:
            context += f" {universe_agent.persona}"

        # Add goal if available
        if universe_agent and universe_agent.goal:
            context += f" Your goal: {universe_agent.goal}"

        # Add accessible sites
        if self.universe and self.universe.sites:
            context += f"\nYou can access: {', '.join(self.universe.sites)}"

        return context

    def _create_llm(self):
        """Create LLM based on model config."""
        from .llm import create_chat_openai

        return create_chat_openai(self.config.model)

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
        self, agent_config: TaskAgentConfig, task: Task, start_url: str, autonomy_level: str = "L1"
    ) -> AgentResult:
        """Run a single agent and return its result."""
        from browser_use import Agent

        start_time = time.time()
        browser = None

        try:
            # Create fresh browser for this agent
            browser = await self._create_browser()

            # Build agent context from universe config
            agent_context = self._build_agent_context(agent_config)

            # Build login hint from agent's credentials
            login_hint = ""
            if agent_config.require_login and agent_config.username and agent_config.password:
                login_hint = f"Login with username '{agent_config.username}' and password '{agent_config.password}'. "

            # Use autonomy level if available, otherwise fall back to task intent
            task_instruction = agent_config.autonomy_levels.get(autonomy_level, task.intent)
            full_task = (
                f"{agent_context}\n\n"
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
                    agent_role="",
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
                agent_role="",
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
                agent_role="",
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
        self, agents: list[TaskAgentConfig], task: Task, start_url: str, autonomy_level: str = "L1"
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
                    # Build agent context from universe config
                    agent_context = self._build_agent_context(agent_config)

                    # Build login hint from agent's credentials
                    login_hint = ""
                    if agent_config.require_login and agent_config.username and agent_config.password:
                        login_hint = f"Login with username '{agent_config.username}' and password '{agent_config.password}'. "

                    # Use autonomy level if available, otherwise fall back to task intent
                    task_instruction = agent_config.autonomy_levels.get(autonomy_level, task.intent)
                    full_task = (
                        f"{agent_context}\n\n"
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
                        except Exception:
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
                                agent_role="",
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
                            agent_role="",
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
                            agent_role="",
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
            # Use the last agent's raw_result, page_content, and final_url for the TaskResult
            last_raw_result = agent_results[-1].raw_result if agent_results else None
            last_page_content = agent_results[-1].page_content if agent_results else None
            last_final_url = agent_results[-1].final_url if agent_results else None

            return TaskResult(
                task_id=task.task_id,
                success=all_succeeded,
                agent_results=agent_results,
                agent_answer=combined_answer if combined_answer else None,
                final_url=last_final_url,
                page_content=last_page_content,
                steps=total_steps,
                duration_seconds=time.time() - overall_start,
                raw_result=last_raw_result,
                autonomy_level=autonomy_level,
            )

        finally:
            # Clean up shared browser
            if browser:
                try:
                    await browser.stop()
                except Exception:
                    pass

    async def run_multi_agent_tasks(
        self, tasks: list[Task]
    ) -> list[TaskResult]:
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

            # Activate scene once per task (before autonomy level loop)
            # NOTE: Scene state persists across autonomy levels. This means:
            # - Setup scripts (e.g., seeding emails) run once
            # - L0 sees fresh state, L1/L2 see accumulated state (e.g., emails marked as read)
            # - If you need isolated state per level, run levels separately with --level
            scene_manager = None
            if task.scene_name:
                scene_manager = SceneManager(self.zoo, self.universe_path)
                await scene_manager.load_and_activate_scene(task.scene_name, task_start_time)

            try:
                # Get agents list from task
                agents = list(task.agents.values())

                # Run each task with configured autonomy levels
                for autonomy_level in self.config.autonomy_levels:
                    # Skip if this (task_id, level) was already completed (for resume)
                    if (task.task_id, autonomy_level) in self.config.completed_pairs:
                        print(f"  Skipping task {task.task_id} {autonomy_level} (already completed)")
                        continue

                    if self.config.shared_browser:
                        # Shared browser: run agents sequentially in same browser
                        result = await self._run_shared_browser_task(agents, task, start_url, autonomy_level)
                        all_results.append(result)
                    else:
                        # Separate browsers: run each agent in its own browser concurrently
                        async def run_single_agent_task(agent_config: TaskAgentConfig) -> AgentResult:
                            return await self._run_single_agent(agent_config, task, start_url, autonomy_level)

                        agent_results = await asyncio.gather(
                            *[run_single_agent_task(agent) for agent in agents]
                        )

                        # Aggregate into TaskResult
                        all_succeeded = all(r.success for r in agent_results)
                        combined_answer = "\n\n".join(
                            f"[{r.agent_name}]: {r.answer}" for r in agent_results if r.answer
                        )
                        total_steps = sum(r.steps for r in agent_results)
                        total_duration = sum(r.duration_seconds for r in agent_results)
                        last_raw_result = agent_results[-1].raw_result if agent_results else None
                        # Get page_content and final_url from last agent result
                        last_page_content = agent_results[-1].page_content if agent_results else None
                        last_final_url = agent_results[-1].final_url if agent_results else None

                        task_result = TaskResult(
                            task_id=task.task_id,
                            success=all_succeeded,
                            agent_results=list(agent_results),
                            agent_answer=combined_answer if combined_answer else None,
                            final_url=last_final_url,
                            page_content=last_page_content,
                            steps=total_steps,
                            duration_seconds=total_duration,
                            raw_result=last_raw_result,
                            autonomy_level=autonomy_level,
                        )
                        all_results.append(task_result)
            finally:
                # Clean up scene manager after all autonomy levels are done
                if scene_manager:
                    try:
                        await scene_manager.cleanup()
                    except Exception:
                        pass

        return all_results
