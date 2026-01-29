"""Base class for agent runners."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from .auth import get_credentials_for_agent
from .models import AgentResult, RunConfig, Task, TaskAgentConfig, TaskResult, Universe

if TYPE_CHECKING:
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

        # Add credentials for this agent
        allowed_sites = self.universe.sites if self.universe else []
        credentials_text = get_credentials_for_agent(agent_config.name, allowed_sites)
        if credentials_text:
            context += f"\n\n{credentials_text}"

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
