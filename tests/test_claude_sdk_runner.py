"""Tests for zoo_eval.claude_sdk_runner."""

import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from zoo_eval.claude_sdk_runner import ClaudeSDKRunner
from zoo_eval.models import (
    AgentConfig,
    AgentHarness,
    RunConfig,
    Task,
    TaskAgentConfig,
    Universe,
)


@pytest.fixture
def mock_zoo():
    """Create a mock Zoo instance."""
    zoo = MagicMock()
    zoo.config.proxy_url = "http://localhost:3128"
    zoo.resolve_url.return_value = "https://example.zoo"
    zoo.restart = MagicMock()
    zoo.wait_for_services = MagicMock()
    zoo.reset_databases = MagicMock()
    return zoo


@pytest.fixture
def config():
    """Create a test RunConfig."""
    return RunConfig(
        harness=AgentHarness.CLAUDE_SDK,
        claude_model="sonnet",
        max_steps=10,
        timeout_seconds=60.0,
        headless=True,
    )


@pytest.fixture
def universe():
    """Create a test Universe."""
    return Universe(
        name="test",
        sites=["example.zoo"],
        agents=[
            AgentConfig(
                role="tester",
                name="alice",
                persona="A test user who likes to explore.",
                goal="Complete tasks efficiently",
            )
        ],
        services={},
    )


class TestClaudeSDKRunnerInit:
    """Tests for ClaudeSDKRunner initialization."""

    def test_init_with_defaults(self, mock_zoo):
        """Test initialization with default config."""
        runner = ClaudeSDKRunner(mock_zoo)
        assert runner.zoo == mock_zoo
        assert runner.config is not None
        assert runner._mcp_config is None

    def test_init_with_config(self, mock_zoo, config, universe):
        """Test initialization with custom config."""
        runner = ClaudeSDKRunner(mock_zoo, config, universe=universe)
        assert runner.config == config
        assert runner.universe == universe


class TestClaudeSDKRunnerSetup:
    """Tests for ClaudeSDKRunner.setup()."""

    @pytest.mark.asyncio
    async def test_setup_creates_mcp_config(self, mock_zoo, config):
        """Test that setup creates MCP configuration."""
        runner = ClaudeSDKRunner(mock_zoo, config)
        await runner.setup()

        assert runner._mcp_config is not None
        assert "zoo-playwright" in runner._mcp_config

        mcp_cfg = runner._mcp_config["zoo-playwright"]
        assert mcp_cfg["command"] == "npx"
        assert "@playwright/mcp@latest" in mcp_cfg["args"]
        assert "--browser" in mcp_cfg["args"]
        assert "firefox" in mcp_cfg["args"]

    @pytest.mark.asyncio
    async def test_setup_includes_proxy(self, mock_zoo, config):
        """Test that setup includes proxy when configured."""
        runner = ClaudeSDKRunner(mock_zoo, config)
        await runner.setup()

        mcp_cfg = runner._mcp_config["zoo-playwright"]
        assert "--proxy-server" in mcp_cfg["args"]
        assert "http://localhost:3128" in mcp_cfg["args"]

    @pytest.mark.asyncio
    async def test_setup_includes_ignore_https_errors(self, mock_zoo, config):
        """Test that setup includes --ignore-https-errors."""
        runner = ClaudeSDKRunner(mock_zoo, config)
        await runner.setup()

        mcp_cfg = runner._mcp_config["zoo-playwright"]
        assert "--ignore-https-errors" in mcp_cfg["args"]

    @pytest.mark.asyncio
    async def test_setup_includes_headless(self, mock_zoo, config):
        """Test that setup includes --headless when configured."""
        runner = ClaudeSDKRunner(mock_zoo, config)
        await runner.setup()

        mcp_cfg = runner._mcp_config["zoo-playwright"]
        assert "--headless" in mcp_cfg["args"]

    @pytest.mark.asyncio
    async def test_setup_no_headless_when_false(self, mock_zoo):
        """Test that setup doesn't include --headless when disabled."""
        config = RunConfig(
            harness=AgentHarness.CLAUDE_SDK,
            headless=False,
        )
        runner = ClaudeSDKRunner(mock_zoo, config)
        await runner.setup()

        mcp_cfg = runner._mcp_config["zoo-playwright"]
        assert "--headless" not in mcp_cfg["args"]


class TestClaudeSDKRunnerHelpers:
    """Tests for ClaudeSDKRunner helper methods."""

    def test_get_agent_role(self, mock_zoo, config, universe):
        """Test _get_agent_role returns correct role."""
        runner = ClaudeSDKRunner(mock_zoo, config, universe=universe)
        agent_config = TaskAgentConfig(name="alice")
        role = runner._get_agent_role(agent_config)
        assert role == "tester"

    def test_get_agent_role_unknown_agent(self, mock_zoo, config, universe):
        """Test _get_agent_role returns empty string for unknown agent."""
        runner = ClaudeSDKRunner(mock_zoo, config, universe=universe)
        agent_config = TaskAgentConfig(name="unknown")
        role = runner._get_agent_role(agent_config)
        assert role == ""

    def test_get_agent_role_no_universe(self, mock_zoo, config):
        """Test _get_agent_role returns empty string when no universe."""
        runner = ClaudeSDKRunner(mock_zoo, config)
        agent_config = TaskAgentConfig(name="alice")
        role = runner._get_agent_role(agent_config)
        assert role == ""

    def test_build_agent_context(self, mock_zoo, config, universe):
        """Test _build_agent_context builds correct context."""
        runner = ClaudeSDKRunner(mock_zoo, config, universe=universe)
        agent_config = TaskAgentConfig(name="alice")
        context = runner._build_agent_context(agent_config)

        assert "You are alice" in context
        assert "tester" in context
        assert "A test user who likes to explore" in context
        assert "Complete tasks efficiently" in context
        assert "example.zoo" in context

    def test_build_login_hint_with_credentials(self, mock_zoo, config):
        """Test _build_login_hint with credentials."""
        runner = ClaudeSDKRunner(mock_zoo, config)
        agent_config = TaskAgentConfig(
            name="alice",
            require_login=True,
            username="alice@test.zoo",
            password="secret123",
        )
        hint = runner._build_login_hint(agent_config)

        assert "alice@test.zoo" in hint
        assert "secret123" in hint

    def test_build_login_hint_without_credentials(self, mock_zoo, config):
        """Test _build_login_hint without credentials."""
        runner = ClaudeSDKRunner(mock_zoo, config)
        agent_config = TaskAgentConfig(name="alice", require_login=False)
        hint = runner._build_login_hint(agent_config)
        assert hint == ""

    def test_build_full_task(self, mock_zoo, config, universe):
        """Test _build_full_task builds correct prompt."""
        runner = ClaudeSDKRunner(mock_zoo, config, universe=universe)
        agent_config = TaskAgentConfig(
            name="alice",
            require_login=True,
            username="alice@test.zoo",
            password="secret",
            autonomy_levels={"L1": "Find and click the button"},
        )
        task = Task(
            task_id=1,
            sites=["example.zoo"],
            intent="Default intent",
            start_url="https://example.zoo",
            agents={"alice": agent_config},
        )

        prompt = runner._build_full_task(
            agent_config, task, "https://example.zoo", "L1"
        )

        assert "You are alice" in prompt
        assert "Go to https://example.zoo" in prompt
        assert "alice@test.zoo" in prompt
        assert "Find and click the button" in prompt

    def test_build_full_task_falls_back_to_intent(self, mock_zoo, config, universe):
        """Test _build_full_task falls back to task intent when no autonomy level."""
        runner = ClaudeSDKRunner(mock_zoo, config, universe=universe)
        agent_config = TaskAgentConfig(name="alice")
        task = Task(
            task_id=1,
            sites=["example.zoo"],
            intent="Default task intent",
            start_url="https://example.zoo",
            agents={"alice": agent_config},
        )

        prompt = runner._build_full_task(
            agent_config, task, "https://example.zoo", "L1"
        )

        assert "Default task intent" in prompt


class TestClaudeSDKRunnerIntegration:
    """Integration tests for ClaudeSDKRunner (require API key and running Zoo)."""

    @pytest.mark.skip(reason="Integration test placeholder - requires running Zoo and API key")
    @pytest.mark.asyncio
    async def test_run_single_agent_integration(self, mock_zoo, config, universe):
        """Integration test for single agent execution.

        This test is skipped by default. To run integration tests:
        1. Start the Zoo environment
        2. Set ANTHROPIC_API_KEY environment variable
        3. Run with: pytest -m integration
        """
        pytest.skip("Not implemented - see docstring for requirements")
