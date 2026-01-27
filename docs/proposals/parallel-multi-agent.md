# Proposal: Parallel Multi-Agent Execution (v2)

**Status:** Draft (Revised)
**Author:** Claude
**Date:** 2026-01-26
**Revised:** Based on architecture review feedback

## Problem Statement

The current multi-agent system runs agents **sequentially**, which has several limitations:

1. **No real-time coordination**: Alice sends an email, then Bob runs and checks inbox. There's no back-and-forth negotiation - each agent runs once to completion.

2. **Artificial constraints**: For meeting negotiation, we tell agents "After sending your email, state your proposed times" because Bob can't wait for Alice's response - he just checks what's already there.

3. **Slow execution**: Running agents sequentially adds delays (currently 5 seconds between agents) and total time is sum of all agent durations.

4. **No multi-round negotiation**: Real negotiations require multiple rounds (Alice proposes → Bob counter-proposes → Alice accepts). Current system only supports single-shot execution.

5. **No failure propagation**: If Alice fails mid-task, Bob still runs and wastes resources.

## Goals

- Agents can engage in multi-round coordination
- Agents can wait for conditions (email received, event fired)
- Deterministic synchronization via explicit mechanisms
- Fast failure propagation (one fails → others stop)
- Independent browser instances per agent
- Backwards compatible with sequential execution

## Non-Goals

- Shared browser state between agents (causes state conflicts)
- Automatic coordination detection (explicit is better)
- Dynamic agent spawning mid-task

---

## Recommended Approach: Turn-Based Execution

After architecture review, **true parallelism introduces significant complexity** (cross-process IPC, SDK cancel scope issues, complex failure modes). A **turn-based execution model** provides 80% of the value with 30% of the implementation effort.

### Turn-Based Model Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    TurnBasedOrchestrator                        │
├─────────────────────────────────────────────────────────────────┤
│  Round 1:                                                       │
│    Alice: sends email → signals "needs_response"                │
│    Bob: (skipped - waiting for Alice's email)                   │
│                                                                 │
│  Round 2:                                                       │
│    Alice: (skipped - waiting for Bob's reply)                   │
│    Bob: reads email → replies → signals "complete"              │
│                                                                 │
│  Round 3:                                                       │
│    Alice: reads reply → confirms → signals "complete"           │
│    Bob: (already complete)                                      │
│                                                                 │
│  All agents complete → return results                           │
└─────────────────────────────────────────────────────────────────┘
```

### Why Turn-Based Over True Parallelism

| Aspect | True Parallelism | Turn-Based |
|--------|------------------|------------|
| MCP server isolation | Needs separate processes | Single sequential process |
| SDK cancel scope bugs | Worse with concurrency | Same as current |
| Cross-process IPC | Required for coordination | Not needed |
| Debugging | Hard (race conditions) | Deterministic |
| Time estimate | 60-80 hours | 20-30 hours |
| Email detection | Complex event system | Simple IMAP polling |

### Advantages of Turn-Based

1. **Uses existing infrastructure**: Leverages current `ClaudeSDKRunner` with minimal changes
2. **Deterministic**: Each round executes in predictable order
3. **Simple debugging**: Can log each round's state clearly
4. **Gradual migration**: Can upgrade to true parallelism later if needed
5. **Avoids SDK issues**: No concurrent `query()` calls

---

## Design: Turn-Based Orchestrator

### Agent State Machine

```
                    ┌─────────────┐
                    │   PENDING   │
                    └──────┬──────┘
                           │ run_turn()
                           ▼
               ┌───────────────────────┐
               │       RUNNING         │
               └───────────┬───────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
  ┌─────────────┐ ┌───────────────┐ ┌───────────────┐
  │  WAITING    │ │   COMPLETE    │ │    FAILED     │
  │ (for event) │ │   (success)   │ │   (error)     │
  └─────────────┘ └───────────────┘ └───────────────┘
           │
           │ event received
           ▼
  (back to PENDING for next round)
```

### Core Implementation

```python
# src/zoo_eval/turn_based_runner.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import asyncio
import imaplib
import time

class AgentState(Enum):
    PENDING = "pending"       # Ready to run
    RUNNING = "running"       # Currently executing
    WAITING = "waiting"       # Waiting for event (skip this round)
    COMPLETE = "complete"     # Finished successfully
    FAILED = "failed"         # Encountered error


@dataclass
class AgentTurnContext:
    """State tracked across turns for an agent."""
    name: str
    state: AgentState = AgentState.PENDING
    wait_condition: str | None = None  # e.g., "email_from:alice@snappymail.zoo"
    rounds_completed: int = 0
    last_answer: str | None = None
    error: str | None = None


@dataclass
class TurnContext:
    """Shared context for a coordination task."""
    round_number: int = 0
    events: list[dict] = field(default_factory=list)  # Events that occurred
    agent_signals: dict[str, str] = field(default_factory=dict)  # agent -> last signal


class TurnBasedOrchestrator:
    """Runs agents in turns for multi-round coordination."""

    def __init__(
        self,
        base_runner: ClaudeSDKRunner,
        max_rounds: int = 10,
        round_timeout: float = 120.0,
    ):
        self.runner = base_runner
        self.max_rounds = max_rounds
        self.round_timeout = round_timeout
        self._logger = logging.getLogger(__name__)

    async def run_coordination_task(
        self,
        task: Task,
        agents: list[TaskAgentConfig],
        autonomy_level: str = "L1",
    ) -> list[AgentResult]:
        """Run agents in turns until all complete or max rounds reached."""

        # Initialize agent contexts
        agent_contexts = {
            a.name: AgentTurnContext(name=a.name)
            for a in agents
        }
        turn_context = TurnContext()
        results: dict[str, AgentResult] = {}

        start_url = self.runner.zoo.resolve_url(task.start_url)

        for round_num in range(self.max_rounds):
            turn_context.round_number = round_num
            self._logger.info(f"=== Round {round_num + 1} ===")

            # Check if all agents are done
            active_agents = [
                a for a in agents
                if agent_contexts[a.name].state not in (AgentState.COMPLETE, AgentState.FAILED)
            ]

            if not active_agents:
                self._logger.info("All agents complete")
                break

            # Check for failure - if any agent failed, stop all
            failed = [a for a in agents if agent_contexts[a.name].state == AgentState.FAILED]
            if failed:
                self._logger.error(f"Agent(s) failed: {[a.name for a in failed]}, stopping")
                for a in active_agents:
                    if a.name not in results:
                        results[a.name] = AgentResult(
                            agent_name=a.name,
                            agent_role=self.runner._get_agent_role(a),
                            success=False,
                            error="Cancelled due to other agent failure"
                        )
                break

            # Process each active agent this round
            for agent in active_agents:
                ctx = agent_contexts[agent.name]

                # Check if agent is waiting for an event
                if ctx.state == AgentState.WAITING and ctx.wait_condition:
                    if not await self._check_wait_condition(ctx.wait_condition, turn_context):
                        self._logger.info(f"  {agent.name}: still waiting for {ctx.wait_condition}")
                        continue
                    else:
                        self._logger.info(f"  {agent.name}: wait condition satisfied")
                        ctx.state = AgentState.PENDING

                # Run this agent's turn
                ctx.state = AgentState.RUNNING
                self._logger.info(f"  {agent.name}: running turn {ctx.rounds_completed + 1}")

                try:
                    result = await self._run_agent_turn(
                        agent, task, start_url, autonomy_level, turn_context, ctx
                    )

                    # Parse agent's signal from their answer
                    signal = self._parse_signal(result.answer)
                    turn_context.agent_signals[agent.name] = signal

                    if signal == "complete":
                        ctx.state = AgentState.COMPLETE
                        results[agent.name] = result
                        self._logger.info(f"  {agent.name}: completed")
                    elif signal.startswith("waiting:"):
                        ctx.state = AgentState.WAITING
                        ctx.wait_condition = signal.split(":", 1)[1]
                        self._logger.info(f"  {agent.name}: waiting for {ctx.wait_condition}")
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
                        error=str(e)
                    )
                    self._logger.error(f"  {agent.name}: failed - {e}")

            # Poll for email events between rounds
            await self._poll_email_events(turn_context)

        # Any agent still not complete is a failure
        for agent in agents:
            if agent.name not in results:
                results[agent.name] = AgentResult(
                    agent_name=agent.name,
                    agent_role=self.runner._get_agent_role(agent),
                    success=False,
                    error=f"Did not complete within {self.max_rounds} rounds"
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
        """Run a single turn for an agent."""

        # Build turn-aware prompt
        prompt = self._build_turn_prompt(
            agent, task, start_url, autonomy_level, turn_context, agent_context
        )

        # Use existing runner infrastructure
        return await self.runner._run_single_agent(
            agent, task, start_url, autonomy_level
        )

    def _build_turn_prompt(
        self,
        agent: TaskAgentConfig,
        task: Task,
        start_url: str,
        autonomy_level: str,
        turn_context: TurnContext,
        agent_context: AgentTurnContext,
    ) -> str:
        """Build prompt with turn context."""

        base = self.runner._build_full_task(agent, task, start_url, autonomy_level)

        # Add turn instructions
        turn_section = f"""
## Turn-Based Coordination (Round {turn_context.round_number + 1})

This is a multi-round coordination task. You will run multiple times.

**Your status this round:** {"First turn" if agent_context.rounds_completed == 0 else f"Turn {agent_context.rounds_completed + 1}"}

**How to signal your status:**
At the END of your response, include one of these signals:
- `[SIGNAL: complete]` - You have finished your part of the task
- `[SIGNAL: waiting:email_from:ADDRESS]` - You need to wait for an email from ADDRESS
- `[SIGNAL: continue]` - You have more work to do (default)

**Other agents' status:**
"""
        for name, signal in turn_context.agent_signals.items():
            if name != agent.name:
                turn_section += f"- {name}: {signal}\n"

        if agent_context.last_answer:
            turn_section += f"\n**Your previous answer:**\n{agent_context.last_answer[:500]}..."

        return base + turn_section

    def _parse_signal(self, answer: str | None) -> str:
        """Parse signal from agent's answer."""
        if not answer:
            return "continue"

        import re
        match = re.search(r'\[SIGNAL:\s*([^\]]+)\]', answer, re.IGNORECASE)
        if match:
            return match.group(1).strip().lower()

        # Fallback: check for completion keywords
        if any(word in answer.lower() for word in ["task complete", "finished", "done"]):
            return "complete"

        return "continue"

    async def _check_wait_condition(
        self,
        condition: str,
        turn_context: TurnContext,
    ) -> bool:
        """Check if a wait condition is satisfied."""

        if condition.startswith("email_from:"):
            from_addr = condition.split(":", 1)[1]
            # Check if we've seen an email event from this address
            for event in turn_context.events:
                if event.get("type") == "email" and event.get("from") == from_addr:
                    return True
            return False

        if condition.startswith("agent_complete:"):
            agent_name = condition.split(":", 1)[1]
            return turn_context.agent_signals.get(agent_name) == "complete"

        return True  # Unknown condition, don't block

    async def _poll_email_events(self, turn_context: TurnContext) -> None:
        """Poll for new emails via IMAP and add to events."""
        # Implementation: connect to SnappyMail IMAP and check for new messages
        # This avoids the Matomo integration issues identified in review
        try:
            new_emails = await self._check_imap_for_new_emails()
            for email in new_emails:
                turn_context.events.append({
                    "type": "email",
                    "from": email["from"],
                    "to": email["to"],
                    "subject": email["subject"],
                    "timestamp": time.time(),
                })
                self._logger.info(f"  [event] Email: {email['from']} → {email['to']}")
        except Exception as e:
            self._logger.warning(f"Email polling failed: {e}")

    async def _check_imap_for_new_emails(self) -> list[dict]:
        """Check IMAP for new emails (implementation detail)."""
        # TODO: Implement actual IMAP connection to snappymail
        # For now, return empty - emails will be detected by agent checking inbox
        return []
```

### Task Definition Updates

Add coordination mode to YAML:

```yaml
- id: 301
  intent: "Alice and Bob negotiate a meeting time via email"
  start_url: "https://snappymail.zoo"

  # NEW: Enable turn-based coordination
  coordination:
    mode: turn_based  # "sequential" (default) | "turn_based"
    max_rounds: 10
    round_timeout: 120

  agents:
    alice:
      require_login: true
      username: alice@snappymail.zoo
      password: alice123
      autonomy_levels:
        L1: |
          Email Bob to propose 2-3 meeting times from your calendar.
          After sending, end your response with [SIGNAL: waiting:email_from:bob@snappymail.zoo]

          When you receive Bob's reply, confirm the meeting time and end with [SIGNAL: complete]

    bob:
      require_login: true
      username: bob@snappymail.zoo
      password: bob123
      autonomy_levels:
        L1: |
          Start by checking your inbox for Alice's meeting proposal.
          If no email from Alice yet, end with [SIGNAL: waiting:email_from:alice@snappymail.zoo]

          When you receive Alice's email, compare times to your calendar.
          Reply accepting a time that works, then end with [SIGNAL: complete]
```

### Integration with ClaudeSDKRunner

```python
# In claude_sdk_runner.py

async def run_multi_agent_tasks(self, tasks: list[Task]) -> list[TaskResult]:
    """Run tasks with their defined agents."""

    for task in tasks:
        # Check coordination mode
        coord_mode = task.coordination.get("mode", "sequential") if task.coordination else "sequential"

        if coord_mode == "turn_based":
            # Use turn-based orchestrator
            orchestrator = TurnBasedOrchestrator(
                base_runner=self,
                max_rounds=task.coordination.get("max_rounds", 10),
                round_timeout=task.coordination.get("round_timeout", 120.0),
            )
            agent_results = await orchestrator.run_coordination_task(
                task, list(task.agents.values()), autonomy_level
            )
        else:
            # Existing sequential execution
            agent_results = []
            for agent in task.agents.values():
                result = await self._run_single_agent(agent, task, start_url, autonomy_level)
                agent_results.append(result)

        # ... rest of result aggregation
```

---

## Phase 2: True Parallel Execution (Future)

If turn-based proves insufficient (e.g., need sub-second response times), upgrade to true parallelism with these fixes from the architecture review:

### Fix 1: Atomic CoordinationHub

```python
class CoordinationHub:
    """Thread-safe event bus with atomic check-and-register."""

    async def wait_for(
        self,
        event_type: str,
        timeout: float = 300.0,
        filter_fn: Callable | None = None
    ) -> CoordinationEvent | None:
        deadline = time.time() + timeout
        event_signal = asyncio.Event()

        while time.time() < deadline:
            # ATOMIC: Check existing events AND register waiter under same lock
            async with self._lock:
                for event in reversed(self._events):
                    if event.event_type == event_type:
                        if filter_fn is None or filter_fn(event):
                            return event
                # No match found - register waiter while still holding lock
                self._waiters[event_type].append(event_signal)

            # Wait outside lock
            try:
                remaining = deadline - time.time()
                await asyncio.wait_for(event_signal.wait(), timeout=min(1.0, remaining))
                event_signal.clear()
            except asyncio.TimeoutError:
                pass
            finally:
                # Clean up waiter
                async with self._lock:
                    if event_signal in self._waiters[event_type]:
                        self._waiters[event_type].remove(event_signal)

        return None
```

### Fix 2: Use Redis for Cross-Process IPC

The coordination MCP tools run in separate processes, so they need Redis or HTTP for communication:

```python
# src/zoo_eval/coordination_service.py

import aioredis
from fastapi import FastAPI

app = FastAPI()
redis: aioredis.Redis = None

@app.on_event("startup")
async def startup():
    global redis
    redis = await aioredis.from_url("redis://localhost:6379")

@app.post("/publish")
async def publish_event(event: CoordinationEvent):
    await redis.publish(f"coord:{event.event_type}", event.json())
    await redis.lpush("coord:events", event.json())
    return {"published": True}

@app.get("/wait/{event_type}")
async def wait_for_event(event_type: str, timeout: float = 300.0):
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"coord:{event_type}")

    try:
        async with asyncio.timeout(timeout):
            async for message in pubsub.listen():
                if message["type"] == "message":
                    return json.loads(message["data"])
    except asyncio.TimeoutError:
        return {"found": False, "reason": "timeout"}
    finally:
        await pubsub.unsubscribe()
```

### Fix 3: IMAP Polling Instead of Matomo

```python
async def poll_email_via_imap(
    mailbox: str,
    from_address: str | None = None,
    subject_contains: str | None = None,
    timeout: float = 300.0,
    poll_interval: float = 2.0,
) -> dict | None:
    """Poll IMAP mailbox for matching emails."""

    deadline = time.time() + timeout
    seen_uids: set[str] = set()

    while time.time() < deadline:
        try:
            async with aioimaplib.IMAP4_SSL('snappymail.zoo') as imap:
                await imap.login(mailbox, get_password(mailbox))
                await imap.select('INBOX')

                # Search for new messages
                _, data = await imap.search(None, 'UNSEEN')
                uids = data[0].split()

                for uid in uids:
                    if uid in seen_uids:
                        continue
                    seen_uids.add(uid)

                    _, msg_data = await imap.fetch(uid, '(RFC822)')
                    email = parse_email(msg_data)

                    if from_address and email['from'] != from_address:
                        continue
                    if subject_contains and subject_contains not in email['subject']:
                        continue

                    return email

        except Exception as e:
            logger.warning(f"IMAP poll error: {e}")

        await asyncio.sleep(poll_interval)

    return None
```

### Fix 4: MCP Cleanup Wrapper

```python
async def _run_agent_with_cleanup(
    agent: TaskAgentConfig,
    task: Task,
    hub: CoordinationHub,
    run_id: str,
) -> AgentResult:
    """Run agent with guaranteed MCP cleanup."""

    # Create isolated browser profile for this agent + run
    profile_dir = f"/tmp/zoo-browser-{run_id}-{agent.name}"

    try:
        return await _run_agent_with_coordination(agent, task, hub)
    finally:
        # Explicit cleanup regardless of how we exit
        try:
            # Kill any orphaned browser processes
            await asyncio.create_subprocess_exec(
                "pkill", "-f", f"--user-data-dir={profile_dir}"
            )
            # Remove profile directory
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Cleanup failed for {agent.name}: {e}")
```

### Fix 5: Structured Logging

```python
import structlog

logger = structlog.get_logger()

class CoordinationHub:
    async def wait_for(self, event_type: str, ...) -> CoordinationEvent | None:
        logger.info(
            "agent_waiting",
            agent=self._current_agent,
            event_type=event_type,
            timeout=timeout,
        )

        result = await self._wait_for_impl(event_type, timeout, filter_fn)

        logger.info(
            "agent_unblocked",
            agent=self._current_agent,
            event_type=event_type,
            found=result is not None,
            waited_ms=int((time.time() - start) * 1000),
        )

        return result
```

---

## Implementation Plan (Turn-Based)

### Phase 1: TurnBasedOrchestrator (8-10 hours)
- Implement `TurnBasedOrchestrator` class
- Agent state machine (PENDING → RUNNING → WAITING/COMPLETE/FAILED)
- Signal parsing from agent answers
- Unit tests

### Phase 2: IMAP Email Detection (6-8 hours)
- Implement IMAP connection to SnappyMail
- Email polling between rounds
- Wait condition checking

### Phase 3: Task/Prompt Updates (4-6 hours)
- Add `coordination.mode` to task YAML parsing
- Update coordination task prompts with signal instructions
- Test with task 301 (2-agent meeting)

### Phase 4: Testing & Polish (4-6 hours)
- End-to-end test with meeting negotiation
- Test 3-agent coordination (task 302)
- Error handling edge cases

**Total (Turn-Based): 22-30 hours**

### Future: True Parallelism (Additional 40-50 hours)
- CoordinationHub with Redis IPC
- Coordination MCP server
- Per-agent process isolation
- Advanced failure propagation

---

## Success Metrics

1. **2-agent negotiation completes** with Alice sending proposal → Bob replying → Alice confirming
2. **<3 rounds** for simple meeting negotiation
3. **Failure propagation**: If Alice fails in round 2, Bob stops immediately
4. **Sequential mode unaffected**: Backwards compatible
5. **3-agent coordination works** (task 302)

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/zoo_eval/turn_based_runner.py` | New file: TurnBasedOrchestrator |
| `src/zoo_eval/claude_sdk_runner.py` | Add coordination mode check, call orchestrator |
| `src/zoo_eval/models.py` | Add `coordination` field to Task |
| `pet_to_wild/.../coordination.yaml` | Update prompts with signals |
| `tests/test_turn_based.py` | New tests for orchestrator |

---

## Open Questions

1. **Should signals be structured?** Current: `[SIGNAL: waiting:email_from:x]`. Alternative: JSON format for richer data.

2. **How to handle "stuck" agents?** If an agent signals waiting but the condition never fires, when do we fail?

3. **Should we support agent "handoff"?** Alice passes control to Bob explicitly, rather than round-robin.

---

## Appendix: Example Session (Turn-Based)

```
=== Task 301: Meeting Negotiation ===
Starting turn-based coordination with 2 agents

=== Round 1 ===
  alice: running turn 1
    💭 I'll email Bob to propose meeting times...
    [1] browser_navigate → https://snappymail.zoo
    [2] browser_type → alice@snappymail.zoo
    [3] browser_click → Login
    [4] browser_click → Compose
    [5] browser_type → bob@snappymail.zoo
    [6] browser_type → Meeting times: Wed 10am, Wed 2pm, Thu 2pm
    [7] browser_click → Send
    💭 Email sent. [SIGNAL: waiting:email_from:bob@snappymail.zoo]
  alice: waiting for email_from:bob@snappymail.zoo

  bob: running turn 1
    💭 Let me check my inbox for Alice's email...
    [1] browser_navigate → https://snappymail.zoo
    [2] browser_type → bob@snappymail.zoo
    [3] browser_click → Login
    [4] browser_click → Inbox
    💭 I see Alice's email! Checking calendar...
    [5] browser_click → Alice's email
    [6] browser_click → Reply
    [7] browser_type → Wed 10am works for me!
    [8] browser_click → Send
    💭 Replied to Alice. [SIGNAL: complete]
  bob: completed

  [event] Email: bob@snappymail.zoo → alice@snappymail.zoo

=== Round 2 ===
  alice: wait condition satisfied (email_from:bob)
  alice: running turn 2
    💭 Let me check Bob's reply...
    [1] browser_click → Inbox
    [2] browser_click → Bob's reply
    💭 Bob accepted Wed 10am. Meeting confirmed!
    [SIGNAL: complete]
  alice: completed

All agents complete

Results:
  alice: SUCCESS - "Meeting scheduled for Wednesday at 10am"
  bob: SUCCESS - "Accepted Wednesday 10am meeting with Alice"
```
