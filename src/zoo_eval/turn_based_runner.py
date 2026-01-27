"""Turn-based multi-agent orchestrator for coordination tasks."""

from __future__ import annotations

import asyncio
import gc
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from .models import AgentResult, Task, TaskAgentConfig

# Delay between agent turns to allow SDK async cleanup
INTER_TURN_DELAY_SECONDS = 5

if TYPE_CHECKING:
    from .claude_sdk_runner import ClaudeSDKRunner


class AgentState(Enum):
    """State of an agent in turn-based execution."""

    PENDING = "pending"  # Ready to run
    RUNNING = "running"  # Currently executing
    WAITING = "waiting"  # Waiting for event (skip this round)
    COMPLETE = "complete"  # Finished successfully
    FAILED = "failed"  # Encountered error


@dataclass
class AgentTurnContext:
    """State tracked across turns for an agent."""

    name: str
    state: AgentState = AgentState.PENDING
    wait_condition: str | None = None  # e.g., "email_from:alice@snappymail.zoo"
    rounds_completed: int = 0
    last_answer: str | None = None
    error: str | None = None
    total_steps: int = 0
    total_duration: float = 0.0


@dataclass
class TurnContext:
    """Shared context for a coordination task."""

    round_number: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)  # Events that occurred
    agent_signals: dict[str, str] = field(default_factory=dict)  # agent -> last signal


class TurnBasedOrchestrator:
    """Runs agents in turns for multi-round coordination.

    Instead of running agents sequentially once each, this orchestrator
    runs agents in rounds, allowing them to wait for conditions (like
    receiving an email) and respond to each other's actions.

    Example flow for meeting negotiation:
        Round 1: Alice sends email, signals "waiting:email_from:bob"
                 Bob checks inbox, sees email, replies, signals "complete"
        Round 2: Alice reads reply, confirms, signals "complete"
                 All agents complete
    """

    def __init__(
        self,
        base_runner: ClaudeSDKRunner,
        max_rounds: int = 10,
        round_timeout: float = 120.0,
    ):
        """Initialize the orchestrator.

        Args:
            base_runner: The ClaudeSDKRunner to use for individual agent turns
            max_rounds: Maximum rounds before failing (default 10)
            round_timeout: Timeout per agent turn in seconds (default 120)
        """
        self.runner = base_runner
        self.max_rounds = max_rounds
        self.round_timeout = round_timeout
        self._logger = logging.getLogger(__name__)

    async def run_coordination_task(
        self,
        task: Task,
        agents: list[TaskAgentConfig],
        start_url: str,
        autonomy_level: str = "L1",
    ) -> list[AgentResult]:
        """Run agents in turns until all complete or max rounds reached.

        Args:
            task: The task to execute
            agents: List of agent configurations
            start_url: Resolved start URL for the task
            autonomy_level: Which autonomy level to use (L0, L1, L2)

        Returns:
            List of AgentResult, one per agent
        """
        # Initialize agent contexts
        agent_contexts = {a.name: AgentTurnContext(name=a.name) for a in agents}
        turn_context = TurnContext()
        results: dict[str, AgentResult] = {}

        self._logger.info(f"Starting turn-based coordination with {len(agents)} agents")

        for round_num in range(self.max_rounds):
            turn_context.round_number = round_num
            print(f"\n=== Round {round_num + 1} ===")

            # Check if all agents are done
            active_agents = [
                a
                for a in agents
                if agent_contexts[a.name].state
                not in (AgentState.COMPLETE, AgentState.FAILED)
            ]

            if not active_agents:
                print("All agents complete")
                break

            # Check for failure - if any agent failed, stop all
            failed = [
                a for a in agents if agent_contexts[a.name].state == AgentState.FAILED
            ]
            if failed:
                print(f"Agent(s) failed: {[a.name for a in failed]}, stopping all")
                for a in active_agents:
                    if a.name not in results:
                        results[a.name] = AgentResult(
                            agent_name=a.name,
                            agent_role=self.runner._get_agent_role(a),
                            success=False,
                            error="Cancelled due to other agent failure",
                        )
                break

            # Track if any agent ran this round
            any_agent_ran = False

            # Process each active agent this round
            for agent in active_agents:
                # Check if any agent has failed - stop immediately
                if any(agent_contexts[a.name].state == AgentState.FAILED for a in agents):
                    break

                ctx = agent_contexts[agent.name]

                # Check if agent is waiting for an event
                if ctx.state == AgentState.WAITING and ctx.wait_condition:
                    if not self._check_wait_condition(ctx.wait_condition, turn_context):
                        print(f"  {agent.name}: still waiting for {ctx.wait_condition}")
                        continue
                    else:
                        print(f"  {agent.name}: wait condition satisfied")
                        ctx.state = AgentState.PENDING

                # Run this agent's turn
                ctx.state = AgentState.RUNNING
                any_agent_ran = True
                print(f"  {agent.name}: running turn {ctx.rounds_completed + 1}")

                # Force cleanup before each agent - SDK has async context issues
                gc.collect()
                if ctx.rounds_completed > 0 or agent != active_agents[0]:
                    # Delay between turns for SDK cleanup (not before very first turn)
                    await asyncio.sleep(INTER_TURN_DELAY_SECONDS)

                try:
                    # Run in isolated task to prevent cancel scope leakage
                    result = await asyncio.create_task(
                        self._run_agent_turn(
                            agent, task, start_url, autonomy_level, turn_context, ctx
                        )
                    )

                    # Accumulate stats
                    ctx.total_steps += result.steps
                    ctx.total_duration += result.duration_seconds

                    # Parse agent's signal from their answer
                    signal = self._parse_signal(result.answer)
                    turn_context.agent_signals[agent.name] = signal

                    # Record email sent event if agent just sent one (check for all signals)
                    if "email" in (result.answer or "").lower() and "sent" in (
                        result.answer or ""
                    ).lower():
                        turn_context.events.append(
                            {
                                "type": "email",
                                "from": agent.username or f"{agent.name}@snappymail.zoo",
                                "timestamp": time.time(),
                            }
                        )
                        print(f"  [event] Email sent by {agent.name}")

                    if signal == "complete":
                        ctx.state = AgentState.COMPLETE
                        # Create final result with accumulated stats
                        results[agent.name] = AgentResult(
                            agent_name=result.agent_name,
                            agent_role=result.agent_role,
                            success=True,
                            answer=result.answer,
                            final_url=result.final_url,
                            page_content=result.page_content,
                            steps=ctx.total_steps,
                            duration_seconds=ctx.total_duration,
                            raw_result=result.raw_result,
                        )
                        print(f"  {agent.name}: completed")
                    elif signal.startswith("waiting:"):
                        ctx.state = AgentState.WAITING
                        ctx.wait_condition = signal[8:]  # Remove "waiting:" prefix
                        print(f"  {agent.name}: waiting for {ctx.wait_condition}")
                    else:
                        # Continue to next round
                        ctx.state = AgentState.PENDING

                    ctx.rounds_completed += 1
                    ctx.last_answer = result.answer

                except Exception as e:
                    ctx.state = AgentState.FAILED
                    ctx.error = str(e)
                    results[agent.name] = AgentResult(
                        agent_name=agent.name,
                        agent_role=self.runner._get_agent_role(agent),
                        success=False,
                        error=str(e),
                        steps=ctx.total_steps,
                        duration_seconds=ctx.total_duration,
                    )
                    print(f"  {agent.name}: failed - {e}")

            # If no agent ran this round, we might be deadlocked
            if not any_agent_ran:
                print("  No agents ran this round - checking for deadlock")
                # Check if all remaining agents are waiting
                waiting_agents = [
                    a
                    for a in active_agents
                    if agent_contexts[a.name].state == AgentState.WAITING
                ]
                if len(waiting_agents) == len(active_agents):
                    print("  Deadlock detected: all agents waiting")
                    for a in waiting_agents:
                        ctx = agent_contexts[a.name]
                        results[a.name] = AgentResult(
                            agent_name=a.name,
                            agent_role=self.runner._get_agent_role(a),
                            success=False,
                            error=f"Deadlock: waiting for {ctx.wait_condition}",
                            steps=ctx.total_steps,
                            duration_seconds=ctx.total_duration,
                        )
                    break

        # Any agent still not complete is a failure
        for agent in agents:
            if agent.name not in results:
                ctx = agent_contexts[agent.name]
                results[agent.name] = AgentResult(
                    agent_name=agent.name,
                    agent_role=self.runner._get_agent_role(agent),
                    success=False,
                    error=f"Did not complete within {self.max_rounds} rounds",
                    steps=ctx.total_steps,
                    duration_seconds=ctx.total_duration,
                )

        return [results[a.name] for a in agents]

    async def _run_agent_turn(
        self,
        agent: TaskAgentConfig,
        task: Task,
        start_url: str,
        autonomy_level: str,
        turn_context: TurnContext,
        agent_context: AgentTurnContext,
    ) -> AgentResult:
        """Run a single turn for an agent.

        Builds a turn-aware prompt and delegates to the base runner.
        """
        # Create a modified task with turn-aware prompt
        turn_prompt = self._build_turn_prompt(
            agent, task, autonomy_level, turn_context, agent_context
        )

        # Create modified agent config with turn prompt
        modified_agent = TaskAgentConfig(
            name=agent.name,
            require_login=agent.require_login,
            username=agent.username,
            password=agent.password,
            autonomy_levels={autonomy_level: turn_prompt},
        )

        # Use existing runner infrastructure
        return await self.runner._run_single_agent(
            modified_agent, task, start_url, autonomy_level
        )

    def _build_turn_prompt(
        self,
        agent: TaskAgentConfig,
        task: Task,
        autonomy_level: str,
        turn_context: TurnContext,
        agent_context: AgentTurnContext,
    ) -> str:
        """Build prompt with turn context and signal instructions."""
        # Get base task instruction
        base_instruction = agent.autonomy_levels.get(autonomy_level, task.intent)

        # Build turn context section
        turn_section = f"""
## Turn-Based Coordination (Round {turn_context.round_number + 1})

This is a multi-round coordination task. You may run multiple times.

**Your status:** {"First turn" if agent_context.rounds_completed == 0 else f"Turn {agent_context.rounds_completed + 1}"}

**IMPORTANT - Signal your status at the END of your response:**
- `[SIGNAL: complete]` - You have finished your part of the task
- `[SIGNAL: waiting:email_from:ADDRESS]` - You need to wait for an email from ADDRESS
- `[SIGNAL: continue]` - You have more work to do

**Other agents' status:**"""

        for name, signal in turn_context.agent_signals.items():
            if name != agent.name:
                turn_section += f"\n- {name}: {signal}"

        if not turn_context.agent_signals:
            turn_section += "\n- (no signals yet)"

        if agent_context.last_answer:
            # Truncate to avoid context overflow
            prev = agent_context.last_answer[:500]
            if len(agent_context.last_answer) > 500:
                prev += "..."
            turn_section += f"\n\n**Your previous response:**\n{prev}"

        return f"{base_instruction}\n{turn_section}"

    def _parse_signal(self, answer: str | None) -> str:
        """Parse signal from agent's answer.

        Looks for [SIGNAL: xxx] pattern, falls back to keyword detection.
        """
        if not answer:
            return "continue"

        # Look for explicit signal
        match = re.search(r"\[SIGNAL:\s*([^\]]+)\]", answer, re.IGNORECASE)
        if match:
            return match.group(1).strip().lower()

        # Fallback: check for completion keywords
        lower = answer.lower()
        if any(
            phrase in lower
            for phrase in [
                "task complete",
                "task is complete",
                "finished",
                "meeting confirmed",
                "meeting scheduled",
            ]
        ):
            return "complete"

        return "continue"

    def _check_wait_condition(
        self,
        condition: str,
        turn_context: TurnContext,
    ) -> bool:
        """Check if a wait condition is satisfied.

        Supports:
        - email_from:ADDRESS - Wait for email from specific address
        - agent_complete:NAME - Wait for another agent to complete
        """
        if condition.startswith("email_from:"):
            from_addr = condition[11:]  # Remove prefix
            # Check if we've seen an email event from this address
            for event in turn_context.events:
                if event.get("type") == "email":
                    event_from = event.get("from", "")
                    # Partial match (e.g., "bob" matches "bob@snappymail.zoo")
                    if from_addr in event_from or event_from in from_addr:
                        return True
            return False

        if condition.startswith("agent_complete:"):
            agent_name = condition[15:]  # Remove prefix
            return turn_context.agent_signals.get(agent_name) == "complete"

        # Unknown condition - don't block
        return True
