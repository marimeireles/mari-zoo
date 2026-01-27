"""Tests for turn_based_runner module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoo_eval.turn_based_runner import (
    AgentState,
    AgentTurnContext,
    TurnBasedOrchestrator,
    TurnContext,
)
from zoo_eval.models import AgentResult, Task, TaskAgentConfig, CoordinationConfig, CoordinationMode


class TestAgentState:
    """Tests for AgentState enum."""

    def test_states_exist(self):
        """All expected states are defined."""
        assert AgentState.PENDING.value == "pending"
        assert AgentState.RUNNING.value == "running"
        assert AgentState.WAITING.value == "waiting"
        assert AgentState.COMPLETE.value == "complete"
        assert AgentState.FAILED.value == "failed"


class TestAgentTurnContext:
    """Tests for AgentTurnContext dataclass."""

    def test_default_values(self):
        """Default values are set correctly."""
        ctx = AgentTurnContext(name="alice")
        assert ctx.name == "alice"
        assert ctx.state == AgentState.PENDING
        assert ctx.wait_condition is None
        assert ctx.rounds_completed == 0
        assert ctx.last_answer is None
        assert ctx.error is None

    def test_all_values(self):
        """Can set all values."""
        ctx = AgentTurnContext(
            name="bob",
            state=AgentState.WAITING,
            wait_condition="email_from:alice@test.zoo",
            rounds_completed=2,
            last_answer="Previous answer",
            error=None,
        )
        assert ctx.state == AgentState.WAITING
        assert ctx.wait_condition == "email_from:alice@test.zoo"
        assert ctx.rounds_completed == 2


class TestTurnContext:
    """Tests for TurnContext dataclass."""

    def test_default_values(self):
        """Default values are set correctly."""
        ctx = TurnContext()
        assert ctx.round_number == 0
        assert ctx.events == []
        assert ctx.agent_signals == {}

    def test_events_and_signals(self):
        """Can add events and signals."""
        ctx = TurnContext()
        ctx.events.append({"type": "email", "from": "alice@test.zoo"})
        ctx.agent_signals["alice"] = "complete"

        assert len(ctx.events) == 1
        assert ctx.agent_signals["alice"] == "complete"


class TestSignalParsing:
    """Tests for signal parsing."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with mock runner."""
        mock_runner = MagicMock()
        return TurnBasedOrchestrator(mock_runner)

    def test_parse_complete_signal(self, orchestrator):
        """Parses [SIGNAL: complete] correctly."""
        answer = "I finished the task. [SIGNAL: complete]"
        assert orchestrator._parse_signal(answer) == "complete"

    def test_parse_waiting_signal(self, orchestrator):
        """Parses [SIGNAL: waiting:...] correctly."""
        answer = "Email sent. [SIGNAL: waiting:email_from:bob@test.zoo]"
        assert orchestrator._parse_signal(answer) == "waiting:email_from:bob@test.zoo"

    def test_parse_continue_signal(self, orchestrator):
        """Parses [SIGNAL: continue] correctly."""
        answer = "Still working. [SIGNAL: continue]"
        assert orchestrator._parse_signal(answer) == "continue"

    def test_parse_case_insensitive(self, orchestrator):
        """Signal parsing is case insensitive."""
        answer = "[signal: COMPLETE]"
        assert orchestrator._parse_signal(answer) == "complete"

    def test_parse_no_signal_defaults_continue(self, orchestrator):
        """No signal defaults to continue."""
        answer = "Just some text without a signal"
        assert orchestrator._parse_signal(answer) == "continue"

    def test_parse_none_returns_continue(self, orchestrator):
        """None answer returns continue."""
        assert orchestrator._parse_signal(None) == "continue"

    def test_parse_fallback_complete_keywords(self, orchestrator):
        """Fallback detection for completion keywords."""
        assert orchestrator._parse_signal("Task complete!") == "complete"
        assert orchestrator._parse_signal("I have finished.") == "complete"
        assert orchestrator._parse_signal("Meeting confirmed for Monday") == "complete"

    def test_parse_signal_with_whitespace(self, orchestrator):
        """Handles whitespace in signals."""
        answer = "[SIGNAL:   complete  ]"
        assert orchestrator._parse_signal(answer) == "complete"


class TestWaitConditionChecking:
    """Tests for wait condition checking."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with mock runner."""
        mock_runner = MagicMock()
        return TurnBasedOrchestrator(mock_runner)

    def test_email_from_exact_match(self, orchestrator):
        """email_from condition matches exact address."""
        ctx = TurnContext()
        ctx.events.append({"type": "email", "from": "alice@snappymail.zoo"})

        assert orchestrator._check_wait_condition(
            "email_from:alice@snappymail.zoo", ctx
        )

    def test_email_from_partial_match(self, orchestrator):
        """email_from condition matches partial address."""
        ctx = TurnContext()
        ctx.events.append({"type": "email", "from": "alice@snappymail.zoo"})

        # Should match "alice" as partial
        assert orchestrator._check_wait_condition("email_from:alice", ctx)

    def test_email_from_no_match(self, orchestrator):
        """email_from condition returns False when no match."""
        ctx = TurnContext()
        ctx.events.append({"type": "email", "from": "bob@snappymail.zoo"})

        assert not orchestrator._check_wait_condition(
            "email_from:alice@snappymail.zoo", ctx
        )

    def test_email_from_no_events(self, orchestrator):
        """email_from condition returns False with no events."""
        ctx = TurnContext()
        assert not orchestrator._check_wait_condition("email_from:alice", ctx)

    def test_agent_complete_match(self, orchestrator):
        """agent_complete condition matches."""
        ctx = TurnContext()
        ctx.agent_signals["bob"] = "complete"

        assert orchestrator._check_wait_condition("agent_complete:bob", ctx)

    def test_agent_complete_no_match(self, orchestrator):
        """agent_complete condition returns False when not complete."""
        ctx = TurnContext()
        ctx.agent_signals["bob"] = "waiting:email_from:alice"

        assert not orchestrator._check_wait_condition("agent_complete:bob", ctx)

    def test_unknown_condition_returns_true(self, orchestrator):
        """Unknown condition types return True (don't block)."""
        ctx = TurnContext()
        assert orchestrator._check_wait_condition("unknown:something", ctx)


class TestTurnPromptBuilding:
    """Tests for turn prompt building."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with mock runner."""
        mock_runner = MagicMock()
        mock_runner._build_full_task = MagicMock(return_value="Base task")
        return TurnBasedOrchestrator(mock_runner)

    def test_first_turn_prompt(self, orchestrator):
        """First turn prompt includes correct status."""
        agent = TaskAgentConfig(
            name="alice",
            autonomy_levels={"L1": "Do the task"},
        )
        task = MagicMock()
        task.intent = "Test intent"
        turn_ctx = TurnContext(round_number=0)
        agent_ctx = AgentTurnContext(name="alice", rounds_completed=0)

        prompt = orchestrator._build_turn_prompt(agent, task, "L1", turn_ctx, agent_ctx)

        assert "Round 1" in prompt
        assert "First turn" in prompt
        assert "[SIGNAL: complete]" in prompt

    def test_subsequent_turn_prompt(self, orchestrator):
        """Subsequent turn prompt includes previous answer."""
        agent = TaskAgentConfig(
            name="alice",
            autonomy_levels={"L1": "Do the task"},
        )
        task = MagicMock()
        task.intent = "Test intent"
        turn_ctx = TurnContext(round_number=1)
        agent_ctx = AgentTurnContext(
            name="alice",
            rounds_completed=1,
            last_answer="Previous response here",
        )

        prompt = orchestrator._build_turn_prompt(agent, task, "L1", turn_ctx, agent_ctx)

        assert "Round 2" in prompt
        assert "Turn 2" in prompt
        assert "Previous response here" in prompt

    def test_other_agents_status_shown(self, orchestrator):
        """Other agents' status is shown in prompt."""
        agent = TaskAgentConfig(
            name="alice",
            autonomy_levels={"L1": "Do the task"},
        )
        task = MagicMock()
        task.intent = "Test intent"
        turn_ctx = TurnContext(round_number=1)
        turn_ctx.agent_signals["bob"] = "complete"
        agent_ctx = AgentTurnContext(name="alice")

        prompt = orchestrator._build_turn_prompt(agent, task, "L1", turn_ctx, agent_ctx)

        assert "bob: complete" in prompt


class TestCoordinationConfig:
    """Tests for CoordinationConfig model."""

    def test_default_values(self):
        """Default values are sequential mode."""
        config = CoordinationConfig()
        assert config.mode == CoordinationMode.SEQUENTIAL
        assert config.max_rounds == 10
        assert config.round_timeout == 120.0

    def test_from_dict_none(self):
        """from_dict with None returns defaults."""
        config = CoordinationConfig.from_dict(None)
        assert config.mode == CoordinationMode.SEQUENTIAL

    def test_from_dict_turn_based(self):
        """from_dict parses turn_based mode."""
        config = CoordinationConfig.from_dict({
            "mode": "turn_based",
            "max_rounds": 5,
            "round_timeout": 60.0,
        })
        assert config.mode == CoordinationMode.TURN_BASED
        assert config.max_rounds == 5
        assert config.round_timeout == 60.0

    def test_from_dict_sequential(self):
        """from_dict parses sequential mode."""
        config = CoordinationConfig.from_dict({"mode": "sequential"})
        assert config.mode == CoordinationMode.SEQUENTIAL


class TestOrchestratorDeadlockDetection:
    """Tests for deadlock detection in orchestrator."""

    @pytest.fixture
    def mock_runner(self):
        """Create mock runner."""
        runner = MagicMock()
        runner._get_agent_role = MagicMock(return_value="tester")
        return runner

    @pytest.mark.asyncio
    async def test_detects_all_agents_waiting(self, mock_runner):
        """Detects deadlock when all agents are waiting."""
        orchestrator = TurnBasedOrchestrator(mock_runner, max_rounds=3)

        # Create agents that will both wait
        agents = [
            TaskAgentConfig(name="alice", autonomy_levels={"L1": "task"}),
            TaskAgentConfig(name="bob", autonomy_levels={"L1": "task"}),
        ]

        task = MagicMock()
        task.intent = "Test"
        task.agents = {"alice": agents[0], "bob": agents[1]}

        # Mock _run_agent_turn to return waiting signals
        async def mock_turn(*args, **kwargs):
            agent = args[0]
            return AgentResult(
                agent_name=agent.name,
                agent_role="tester",
                success=True,
                answer=f"[SIGNAL: waiting:email_from:other@test.zoo]",
                steps=1,
                duration_seconds=1.0,
            )

        orchestrator._run_agent_turn = mock_turn

        results = await orchestrator.run_coordination_task(task, agents, "http://test", "L1")

        # Both should have failed due to deadlock
        assert len(results) == 2
        assert all(not r.success for r in results)
        assert all("Deadlock" in (r.error or "") for r in results)


class TestOrchestratorFailurePropagation:
    """Tests for failure propagation in orchestrator."""

    @pytest.fixture
    def mock_runner(self):
        """Create mock runner."""
        runner = MagicMock()
        runner._get_agent_role = MagicMock(return_value="tester")
        return runner

    @pytest.mark.asyncio
    async def test_stops_all_on_failure(self, mock_runner):
        """When one agent fails, others are cancelled."""
        orchestrator = TurnBasedOrchestrator(mock_runner, max_rounds=5)

        agents = [
            TaskAgentConfig(name="alice", autonomy_levels={"L1": "task"}),
            TaskAgentConfig(name="bob", autonomy_levels={"L1": "task"}),
        ]

        task = MagicMock()
        task.intent = "Test"
        task.agents = {"alice": agents[0], "bob": agents[1]}

        call_count = {"alice": 0, "bob": 0}

        async def mock_turn(*args, **kwargs):
            agent = args[0]
            call_count[agent.name] += 1

            if agent.name == "alice":
                # Alice fails on first turn
                raise Exception("Alice crashed")
            else:
                return AgentResult(
                    agent_name="bob",
                    agent_role="tester",
                    success=True,
                    answer="[SIGNAL: continue]",
                    steps=1,
                    duration_seconds=1.0,
                )

        orchestrator._run_agent_turn = mock_turn

        results = await orchestrator.run_coordination_task(task, agents, "http://test", "L1")

        # Alice failed, Bob should be cancelled
        alice_result = next(r for r in results if r.agent_name == "alice")
        bob_result = next(r for r in results if r.agent_name == "bob")

        assert not alice_result.success
        assert "Alice crashed" in alice_result.error

        assert not bob_result.success
        assert "other agent failure" in bob_result.error.lower()

        # Bob should not have run after Alice failed
        assert call_count["bob"] == 0
