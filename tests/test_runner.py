"""Tests for zoo_eval.runner module."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

from zoo_eval.runner import create_agent_runner, TaskRunner, RunResult
from zoo_eval.models import (
    AgentHarness,
    RunConfig,
    Task,
    TaskResult,
    TaskAgentConfig,
    Evaluation,
    EvalType,
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
def browser_use_config():
    """RunConfig for browser_use harness."""
    return RunConfig(harness=AgentHarness.BROWSER_USE)


@pytest.fixture
def claude_sdk_config():
    """RunConfig for claude_sdk harness."""
    return RunConfig(harness=AgentHarness.CLAUDE_SDK)


class TestCreateAgentRunner:
    """Tests for create_agent_runner factory function."""

    def test_creates_browser_use_runner_for_browser_use(self, mock_zoo, browser_use_config):
        """Factory returns BrowserUseRunner for BROWSER_USE harness."""
        runner = create_agent_runner(mock_zoo, browser_use_config)

        # Import here to check type
        from zoo_eval.browser_use_runner import BrowserUseRunner

        assert isinstance(runner, BrowserUseRunner)
        assert runner.zoo == mock_zoo
        assert runner.config == browser_use_config

    def test_creates_claude_sdk_runner_for_claude_sdk(self, mock_zoo, claude_sdk_config):
        """Factory returns ClaudeSDKRunner for CLAUDE_SDK harness."""
        runner = create_agent_runner(mock_zoo, claude_sdk_config)

        from zoo_eval.claude_sdk_runner import ClaudeSDKRunner

        assert isinstance(runner, ClaudeSDKRunner)
        assert runner.zoo == mock_zoo
        assert runner.config == claude_sdk_config

    def test_default_harness_creates_browser_use(self, mock_zoo):
        """Default config (no harness specified) creates BrowserUseRunner."""
        config = RunConfig()  # Uses default BROWSER_USE
        runner = create_agent_runner(mock_zoo, config)

        from zoo_eval.browser_use_runner import BrowserUseRunner

        assert isinstance(runner, BrowserUseRunner)

    def test_passes_universe_to_runner(self, mock_zoo, browser_use_config):
        """Factory passes universe_path and universe to runner."""
        from zoo_eval.models import Universe, AgentConfig

        universe = Universe(
            name="test",
            sites=["example.zoo"],
            agents=[AgentConfig(role="tester", name="alice", persona="", goal="")],
            services={},
        )
        universe_path = Path("/fake/path")

        runner = create_agent_runner(
            mock_zoo, browser_use_config, universe_path=universe_path, universe=universe
        )

        assert runner.universe_path == universe_path
        assert runner.universe == universe


class TestRunResult:
    """Tests for RunResult dataclass."""

    def test_score_from_task_result(self):
        """RunResult.score delegates to TaskResult.score."""
        task = Task(
            task_id=1,
            intent="Test",
            sites=[],
            start_url="",
            agents={"alice": TaskAgentConfig(name="alice")},
        )
        task_result = TaskResult(task_id=1, score=1.0)

        run_result = RunResult(task=task, task_result=task_result)
        assert run_result.score == 1.0

    def test_zero_score(self):
        """RunResult.score is 0.0 when task fails."""
        task = Task(
            task_id=1,
            intent="Test",
            sites=[],
            start_url="",
            agents={"alice": TaskAgentConfig(name="alice")},
        )
        task_result = TaskResult(task_id=1, score=0.0)

        run_result = RunResult(task=task, task_result=task_result)
        assert run_result.score == 0.0

    def test_partial_score(self):
        """RunResult.score supports partial scores."""
        task = Task(
            task_id=1,
            intent="Test",
            sites=[],
            start_url="",
            agents={"alice": TaskAgentConfig(name="alice")},
        )
        task_result = TaskResult(task_id=1, score=0.5)

        run_result = RunResult(task=task, task_result=task_result)
        assert run_result.score == 0.5


class TestTaskRunner:
    """Tests for TaskRunner class."""

    @pytest.mark.asyncio
    async def test_setup_creates_agent_runner(self, mock_zoo, browser_use_config):
        """TaskRunner.setup() creates the appropriate agent runner."""
        runner = TaskRunner(mock_zoo, browser_use_config)

        with patch("zoo_eval.runner.create_agent_runner") as mock_factory:
            mock_agent_runner = AsyncMock()
            mock_factory.return_value = mock_agent_runner

            await runner.setup()

            mock_factory.assert_called_once_with(
                mock_zoo, browser_use_config, None, None
            )
            mock_agent_runner.setup.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_and_evaluate_batch(self, mock_zoo, browser_use_config):
        """TaskRunner runs tasks and evaluates results."""
        runner = TaskRunner(mock_zoo, browser_use_config)

        # Create test task
        task = Task(
            task_id=1,
            intent="Test task",
            sites=[],
            start_url="https://example.zoo",
            agents={"alice": TaskAgentConfig(name="alice")},
            evaluation=Evaluation(
                eval_types=[EvalType.STRING_MATCH],
                reference_answers=None,
            ),
        )

        # Mock the agent runner
        mock_agent_runner = AsyncMock()
        task_result = TaskResult(
            task_id=1,
            score=1.0,
            agent_answer="test answer",
            autonomy_level="L1",
        )
        mock_agent_runner.run_tasks.return_value = [task_result]
        runner._agent_runner = mock_agent_runner

        # Mock evaluate_task
        with patch("zoo_eval.runner.evaluate_task") as mock_eval:
            mock_eval.return_value = None  # evaluate_task now mutates task_result in place

            results = await runner.run_and_evaluate_batch([task], "test_universe")

            assert len(results) == 1
            assert results[0].task == task
            assert results[0].task_result == task_result

            # Verify evaluate_task was called with judge_model
            mock_eval.assert_called_once()


class TestTaskRunnerIntegration:
    """Integration tests for TaskRunner (without mocks where possible)."""

    def test_default_config(self, mock_zoo):
        """TaskRunner uses default config if none provided."""
        runner = TaskRunner(mock_zoo)
        assert runner.config is not None
        assert runner.config.harness == AgentHarness.BROWSER_USE
