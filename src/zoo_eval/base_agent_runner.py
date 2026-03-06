"""Base class for agent runners."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from .auth import get_credentials_for_agent
from .models import AgentResult, RunConfig, Task, TaskAgentConfig, TaskResult, Universe

if TYPE_CHECKING:
    from .scenes import SceneManager
    from .zoo import Zoo


class BaseAgentRunner(ABC):
    """Abstract base class for agent runners.

    Provides shared logic for building agent context and universe lookups.
    Subclasses implement harness-specific execution.
    """

    def __init__(
        self,
        zoo: Zoo,
        config: RunConfig | None = None,
        universe_path: Path | None = None,
        universe: Universe | None = None,
    ):
        self.zoo = zoo
        self.config = config or RunConfig()
        self.universe_path = universe_path
        self.universe = universe

    def _get_universe_agent(self, agent_name: str):
        """Get the universe agent config by name."""
        if not self.universe:
            return None
        for agent in self.universe.agents:
            if agent.name == agent_name:
                return agent
        return None

    def _resolve_model(self, agent_config: TaskAgentConfig) -> str:
        """Resolve the model for an agent using hierarchy: Task > Universe > CLI.

        Priority (highest to lowest):
        1. Task agent config model (specified in task file)
        2. Universe agent config model (specified in universe config)
        3. CLI default model (passed via command line / RunConfig)
        """
        # Highest priority: task-level model
        if agent_config.model:
            return agent_config.model

        # Medium priority: universe-level model
        universe_agent = self._get_universe_agent(agent_config.name)
        if universe_agent and universe_agent.model:
            return universe_agent.model

        # Lowest priority: CLI default
        return self.config.model

    def _build_agent_context(self, agent_config: TaskAgentConfig, task: Task | None = None) -> str:
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

        # Add credentials for this agent
        allowed_sites = self.universe.sites if self.universe else []
        credentials_text = get_credentials_for_agent(agent_config.name, allowed_sites)
        if credentials_text:
            context += f"\n\n{credentials_text}"

        # Add sensitive data for injection resistance testing
        if task and task.sensitive_data:
            context += f"\n\n{task.sensitive_data}"

        return context

    def _build_full_task(
        self, agent_config: TaskAgentConfig, task: Task, start_url: str, autonomy_level: str
    ) -> str:
        """Build the task prompt for an agent.

        Note: Agent identity/context and credentials go in extend_system_message.
        """
        # Use autonomy level if available, otherwise fall back to task intent
        task_instruction = agent_config.autonomy_levels.get(autonomy_level, task.intent)

        return f"Go to {start_url}. {task_instruction}"

    @asynccontextmanager
    async def scene_context(self, task: Task) -> AsyncIterator["SceneManager | None"]:
        """Context manager for scene setup and cleanup.

        Handles all the boilerplate of setting up scenes, including:
        - Loading scene configuration from the universe
        - Setting up initial state (emails, repos, boards, etc.)
        - Configuring triggers for dynamic events
        - Cleaning up after the task completes

        Usage:
            async with self.scene_context(task) as scene_manager:
                result = await self._run_agent(...)
                # scene_manager is None if task has no scene

        Args:
            task: The task being run (may or may not have a scene_name)

        Yields:
            SceneManager instance if task has a scene, None otherwise
        """
        if not task.scene_name:
            yield None
            return

        from .scenes import SceneManager
        from .proxy_event_source import ProxyEventSource

        # Determine if we need proxy-based event source
        from .models import load_scene
        scenes_dir = self.universe_path / "scenes" if self.universe_path else None
        scene_path = scenes_dir / f"{task.scene_name}.yaml" if scenes_dir else None
        scene = load_scene(scene_path) if scene_path and scene_path.exists() else None

        use_proxy = self.config.use_proxy_events or (scene and scene.needs_proxy_events)
        event_source = None
        if use_proxy:
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

        try:
            await scene_manager.load_and_setup(task.scene_name)
            await scene_manager.setup_triggers()
            yield scene_manager
        finally:
            try:
                await scene_manager.cleanup()
            except Exception:
                pass

    @abstractmethod
    async def setup(self):
        """Initialize runner-specific components."""
        pass

    @abstractmethod
    async def teardown(self):
        """Clean up resources."""
        pass

    @abstractmethod
    async def _run_single_agent(
        self, agent_config: TaskAgentConfig, task: Task, start_url: str, autonomy_level: str = "L1"
    ) -> AgentResult:
        """Run a single agent and return its result."""
        pass

    @abstractmethod
    async def run_tasks(self, tasks: list[Task]) -> list[TaskResult]:
        """Run tasks with their defined agents."""
        pass
