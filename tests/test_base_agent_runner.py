"""Tests for zoo_eval.base_agent_runner module."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path

from zoo_eval.base_agent_runner import BaseAgentRunner
from zoo_eval.models import (
    AgentConfig,
    AgentResult,
    RunConfig,
    Task,
    TaskAgentConfig,
    TaskResult,
    Universe,
)


class ConcreteRunner(BaseAgentRunner):
    """Concrete implementation for testing the abstract base class."""

    async def setup(self):
        pass

    async def teardown(self):
        pass

    async def _run_single_agent(
        self, agent_config: TaskAgentConfig, task: Task, start_url: str, autonomy_level: str = "L1"
    ) -> AgentResult:
        return AgentResult(
            agent_name=agent_config.name,
            agent_role="test",
            success=True,
        )

    async def run_multi_agent_tasks(self, tasks: list[Task]) -> list[TaskResult]:
        return []


@pytest.fixture
def mock_zoo():
    """Create a mock Zoo instance."""
    zoo = MagicMock()
    zoo.config.proxy_url = "http://localhost:3128"
    return zoo


@pytest.fixture
def simple_universe():
    """Create a simple universe for testing."""
    return Universe(
        name="test_universe",
        sites=["gitea.zoo", "snappymail.zoo"],
        agents=[
            AgentConfig(
                role="developer",
                name="alice",
                persona="A senior developer who writes clean code.",
                goal="Complete coding tasks efficiently.",
            ),
            AgentConfig(
                role="tester",
                name="bob",
                persona="A QA engineer focused on finding bugs.",
                goal="Ensure software quality.",
            ),
        ],
        services={},
    )


@pytest.fixture
def agent_config_with_credentials():
    """Agent config with login credentials."""
    return TaskAgentConfig(
        name="alice",
        require_login=True,
        username="alice@test.zoo",
        password="secret123",
        autonomy_levels={
            "L0": "Step 1: Open the settings. Step 2: Click save.",
            "L1": "Open settings and save your changes.",
            "L2": "Save settings",
        },
    )


@pytest.fixture
def agent_config_minimal():
    """Minimal agent config without credentials."""
    return TaskAgentConfig(name="charlie")


class TestBaseAgentRunnerInit:
    """Tests for BaseAgentRunner initialization."""

    def test_init_with_defaults(self, mock_zoo):
        """Runner initializes with default config if none provided."""
        runner = ConcreteRunner(mock_zoo)

        assert runner.zoo == mock_zoo
        assert runner.config is not None
        assert isinstance(runner.config, RunConfig)
        assert runner.universe_path is None
        assert runner.universe is None

    def test_init_with_config(self, mock_zoo):
        """Runner uses provided config."""
        config = RunConfig(max_steps=50, headless=False)
        runner = ConcreteRunner(mock_zoo, config=config)

        assert runner.config == config
        assert runner.config.max_steps == 50
        assert runner.config.headless is False

    def test_init_with_universe(self, mock_zoo, simple_universe):
        """Runner stores universe info."""
        universe_path = Path("/fake/path")
        runner = ConcreteRunner(
            mock_zoo,
            universe_path=universe_path,
            universe=simple_universe,
        )

        assert runner.universe_path == universe_path
        assert runner.universe == simple_universe


class TestGetUniverseAgent:
    """Tests for _get_universe_agent method."""

    def test_finds_agent_by_name(self, mock_zoo, simple_universe):
        """Returns agent config when found by name."""
        runner = ConcreteRunner(mock_zoo, universe=simple_universe)

        alice = runner._get_universe_agent("alice")
        assert alice is not None
        assert alice.name == "alice"
        assert alice.role == "developer"

    def test_returns_none_for_unknown_agent(self, mock_zoo, simple_universe):
        """Returns None when agent name not found."""
        runner = ConcreteRunner(mock_zoo, universe=simple_universe)

        unknown = runner._get_universe_agent("unknown_agent")
        assert unknown is None

    def test_returns_none_when_no_universe(self, mock_zoo):
        """Returns None when no universe is configured."""
        runner = ConcreteRunner(mock_zoo)

        result = runner._get_universe_agent("alice")
        assert result is None


class TestBuildAgentContext:
    """Tests for _build_agent_context method."""

    def test_basic_context_with_universe(self, mock_zoo, simple_universe, agent_config_with_credentials):
        """Builds context with role, persona, goal, and sites."""
        runner = ConcreteRunner(mock_zoo, universe=simple_universe)

        context = runner._build_agent_context(agent_config_with_credentials)

        assert "You are alice" in context
        assert "a developer" in context
        assert "A senior developer who writes clean code." in context
        assert "Your goal: Complete coding tasks efficiently." in context
        assert "gitea.zoo" in context
        assert "snappymail.zoo" in context

    def test_context_without_universe(self, mock_zoo, agent_config_with_credentials):
        """Builds minimal context when no universe."""
        runner = ConcreteRunner(mock_zoo)

        context = runner._build_agent_context(agent_config_with_credentials)

        assert "You are alice." in context
        # No role, persona, goal, or sites
        assert "developer" not in context
        assert "Your goal" not in context
        assert "can access" not in context

    def test_context_for_unknown_agent(self, mock_zoo, simple_universe):
        """Builds minimal context for agent not in universe."""
        runner = ConcreteRunner(mock_zoo, universe=simple_universe)
        unknown_agent = TaskAgentConfig(name="unknown")

        context = runner._build_agent_context(unknown_agent)

        assert "You are unknown." in context
        # Still has sites from universe
        assert "can access" in context
        # But no role/persona/goal
        assert "Your goal" not in context

    def test_context_with_empty_persona_and_goal(self, mock_zoo):
        """Handles agent with empty persona/goal."""
        universe = Universe(
            name="test",
            sites=["test.zoo"],
            agents=[AgentConfig(role="worker", name="dave", persona="", goal="")],
            services={},
        )
        runner = ConcreteRunner(mock_zoo, universe=universe)
        agent = TaskAgentConfig(name="dave")

        context = runner._build_agent_context(agent)

        assert "You are dave" in context
        assert "a worker" in context
        # Empty persona/goal shouldn't add extra text
        assert context.count("Your goal") == 0

    def test_context_includes_task_specific_context(self, mock_zoo, simple_universe):
        """Task-specific context (like calendar constraints) is included."""
        runner = ConcreteRunner(mock_zoo, universe=simple_universe)
        agent = TaskAgentConfig(
            name="alice",
            context="YOUR CALENDAR CONSTRAINTS:\n- Monday: Free 9am-12pm\n- Tuesday: Busy all day",
        )

        context = runner._build_agent_context(agent)

        assert "You are alice" in context
        assert "YOUR CALENDAR CONSTRAINTS:" in context
        assert "Monday: Free 9am-12pm" in context
        assert "Tuesday: Busy all day" in context


class TestBuildLoginHint:
    """Tests for _build_login_hint method."""

    def test_login_hint_with_credentials(self, mock_zoo, agent_config_with_credentials):
        """Builds login hint when all credentials present."""
        runner = ConcreteRunner(mock_zoo)

        hint = runner._build_login_hint(agent_config_with_credentials)

        assert "alice@test.zoo" in hint
        assert "secret123" in hint
        assert "Login with" in hint

    def test_no_hint_when_login_not_required(self, mock_zoo):
        """Returns empty string when require_login is False."""
        runner = ConcreteRunner(mock_zoo)
        agent = TaskAgentConfig(
            name="test",
            require_login=False,
            username="user",
            password="pass",
        )

        hint = runner._build_login_hint(agent)

        assert hint == ""

    def test_no_hint_when_username_missing(self, mock_zoo):
        """Returns empty string when username is missing."""
        runner = ConcreteRunner(mock_zoo)
        agent = TaskAgentConfig(
            name="test",
            require_login=True,
            username=None,
            password="pass",
        )

        hint = runner._build_login_hint(agent)

        assert hint == ""

    def test_no_hint_when_password_missing(self, mock_zoo):
        """Returns empty string when password is missing."""
        runner = ConcreteRunner(mock_zoo)
        agent = TaskAgentConfig(
            name="test",
            require_login=True,
            username="user",
            password=None,
        )

        hint = runner._build_login_hint(agent)

        assert hint == ""

    def test_no_hint_for_minimal_agent(self, mock_zoo, agent_config_minimal):
        """Returns empty string for minimal agent config."""
        runner = ConcreteRunner(mock_zoo)

        hint = runner._build_login_hint(agent_config_minimal)

        assert hint == ""


class TestBuildFullTask:
    """Tests for _build_full_task method."""

    def test_builds_complete_task_prompt(self, mock_zoo, simple_universe, agent_config_with_credentials):
        """Builds full task with context, login, and instruction."""
        runner = ConcreteRunner(mock_zoo, universe=simple_universe)
        task = Task(
            task_id=1,
            intent="Default task instruction",
            sites=["gitea.zoo"],
            start_url="https://gitea.zoo",
            agents={"alice": agent_config_with_credentials},
        )

        prompt = runner._build_full_task(
            agent_config_with_credentials, task, "https://gitea.zoo", "L1"
        )

        assert "You are alice" in prompt
        assert "Go to https://gitea.zoo" in prompt
        assert "alice@test.zoo" in prompt  # Login hint
        assert "Open settings and save your changes." in prompt  # L1 instruction

    def test_uses_autonomy_level_instruction(self, mock_zoo, agent_config_with_credentials):
        """Uses autonomy level instruction when available."""
        runner = ConcreteRunner(mock_zoo)
        task = Task(
            task_id=1,
            intent="Fallback intent",
            sites=[],
            start_url="",
            agents={"alice": agent_config_with_credentials},
        )

        prompt_l0 = runner._build_full_task(
            agent_config_with_credentials, task, "https://test.zoo", "L0"
        )
        prompt_l2 = runner._build_full_task(
            agent_config_with_credentials, task, "https://test.zoo", "L2"
        )

        assert "Step 1: Open the settings" in prompt_l0  # L0 detailed
        assert "Save settings" in prompt_l2  # L2 minimal

    def test_falls_back_to_intent(self, mock_zoo, agent_config_with_credentials):
        """Falls back to task intent when autonomy level not defined."""
        runner = ConcreteRunner(mock_zoo)
        task = Task(
            task_id=1,
            intent="Do the important thing",
            sites=[],
            start_url="",
            agents={"alice": agent_config_with_credentials},
        )

        prompt = runner._build_full_task(
            agent_config_with_credentials, task, "https://test.zoo", "L3"  # L3 not defined
        )

        assert "Do the important thing" in prompt

    def test_no_login_hint_for_minimal_agent(self, mock_zoo, agent_config_minimal):
        """No login hint for agent without credentials."""
        runner = ConcreteRunner(mock_zoo)
        task = Task(
            task_id=1,
            intent="Just browse",
            sites=[],
            start_url="",
            agents={"charlie": agent_config_minimal},
        )

        prompt = runner._build_full_task(
            agent_config_minimal, task, "https://test.zoo", "L1"
        )

        assert "Login with" not in prompt
        assert "Just browse" in prompt


class TestConcreteImplementation:
    """Tests verifying abstract methods must be implemented."""

    def test_abstract_methods_required(self, mock_zoo):
        """Verifies we can't instantiate BaseAgentRunner directly."""
        with pytest.raises(TypeError, match="abstract"):
            BaseAgentRunner(mock_zoo)

    @pytest.mark.asyncio
    async def test_concrete_runner_works(self, mock_zoo):
        """ConcreteRunner can be instantiated and called."""
        runner = ConcreteRunner(mock_zoo)

        await runner.setup()
        await runner.teardown()
        tasks = await runner.run_multi_agent_tasks([])

        assert tasks == []
