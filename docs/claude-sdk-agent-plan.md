# Plan: Adding Claude Agent SDK as Second Agent Harness

## Overview

This document outlines the plan to add Claude Agent SDK with playwright-mcp as an alternative agentic harness for zoo-eval, enabling side-by-side comparison with the existing browser-use implementation.

**Key Simplification**: Using `claude-agent-sdk` (the high-level SDK) instead of raw `anthropic` + `mcp`. The SDK handles the agentic loop, MCP server lifecycle, and tool execution automatically.

## Goals

1. Support Claude Agent SDK as a first-class agent harness alongside browser-use
2. Maintain consistent evaluation interface across both harnesses
3. Enable comparative benchmarking between harness implementations
4. Preserve all existing browser-use functionality

## Current Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      TaskRunner                         │
│                     (runner.py)                         │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  MultiAgentRunner                       │
│              (multi_agent_runner.py)                    │
│                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌────────────┐  │
│  │  browser-use │    │  ChatOpenAI │    │  Browser   │  │
│  │    Agent     │◄───│    (LLM)    │    │ (Playwright)│  │
│  └─────────────┘    └─────────────┘    └────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      TaskRunner                         │
│                     (runner.py)                         │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                   BaseAgentRunner (ABC)                 │
│                  (base_agent_runner.py)                 │
│                                                         │
│  Shared logic:                                          │
│  - _build_agent_context()                               │
│  - _get_universe_agent()                                │
│  - Service restart & health checks                      │
│  - Scene management                                     │
└─────────────────────────┬───────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
┌─────────────────────────┐ ┌─────────────────────────────┐
│   BrowserUseRunner      │ │   ClaudeSDKRunner           │
│  (multi_agent_runner.py)│ │  (claude_sdk_runner.py)     │
│                         │ │                             │
│  ┌─────────────┐        │ │  ┌─────────────────────┐    │
│  │ browser-use │        │ │  │ claude-agent-sdk    │    │
│  │   Agent     │        │ │  │   query()           │    │
│  └─────────────┘        │ │  └─────────────────────┘    │
│         │               │ │           │                 │
│         ▼               │ │           ▼                 │
│  ┌─────────────┐        │ │  ┌─────────────────────┐    │
│  │  Playwright │        │ │  │  playwright-mcp     │    │
│  │  (direct)   │        │ │  │  (auto-managed)     │    │
│  └─────────────┘        │ │  └─────────────────────┘    │
└─────────────────────────┘ └─────────────────────────────┘
```

## Risk Assessment

### High Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **SDK availability/API mismatch** | Blocks implementation | Complete Phase 0 verification first; have fallback plan |
| **MCP server startup overhead** | Slow per-agent runs | Benchmark in POC; consider server pooling |
| **Timeout not enforced by SDK** | Agents run forever | Use `asyncio.timeout()` wrapper |

### Medium Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Proxy/cert flags not supported** | Can't connect to Zoo | Test in POC with `--proxy-server` and `--ignore-https-errors` |
| **Page content not captured** | `PROGRAM_HTML` evals fail | Add explicit `browser_snapshot` call |
| **Cost tracking inaccurate** | Wrong metrics | Log raw token counts as backup |

### Low Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Different step granularity** | Metrics not comparable | Document differences clearly |
| **API key management** | Runtime errors | Validate in CLI before run |

---

## Fallback Plan

If `claude-agent-sdk` doesn't work as expected, use **browser-use with Claude via LangChain**:

```python
from browser_use import Agent
from langchain_anthropic import ChatAnthropic

# Use Claude model with browser-use framework
llm = ChatAnthropic(model="claude-sonnet-4-20250514")
agent = Agent(task=task, llm=llm, browser=browser)
result = await agent.run(max_steps=30)
```

This gets Claude models without depending on a new SDK, using the existing browser-use infrastructure.

---

## Implementation Plan

### Pre-Phase: SDK Verification

**Before starting any implementation**, verify the SDK exists and works:

```bash
# Step 1: Install SDK
pip install claude-agent-sdk

# Step 2: Verify imports work
python -c "from claude_agent_sdk import query, ClaudeAgentOptions; print('SDK OK')"

# Step 3: Check available exports
python -c "import claude_agent_sdk; print(dir(claude_agent_sdk))"
```

**If this fails**: Use the fallback plan (browser-use + langchain_anthropic).

---

### Phase 0: Proof of Concept (Pre-work)

**Goal**: Validate the Claude Agent SDK with playwright-mcp works as expected.

**File: `scripts/poc_claude_sdk.py`**

```python
"""Proof of concept for Claude Agent SDK + playwright-mcp integration."""

import asyncio
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)


async def main():
    """Test Claude Agent SDK with playwright-mcp."""

    # Configure playwright-mcp as stdio server
    options = ClaudeAgentOptions(
        mcp_servers={
            "playwright": {
                "command": "npx",
                "args": ["@playwright/mcp@latest", "--browser", "firefox"],
            }
        },
        # Allow all playwright tools
        allowed_tools=["mcp__playwright__*"],
        # Model selection
        model="sonnet",
        # Max turns to prevent infinite loops
        max_turns=20,
    )

    # Run the agent - SDK handles the agentic loop automatically
    steps = 0
    final_text = None

    async for message in query(
        prompt="Navigate to https://example.com and tell me the page title",
        options=options,
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"Assistant: {block.text[:100]}...")
                elif isinstance(block, ToolUseBlock):
                    steps += 1
                    print(f"Tool call #{steps}: {block.name}")

        elif isinstance(message, ResultMessage):
            print(f"\n--- Complete ---")
            print(f"Success: {not message.is_error}")
            print(f"Turns: {message.num_turns}")
            print(f"Duration: {message.duration_ms}ms")
            print(f"Cost: ${message.total_cost_usd}")
            print(f"Result: {message.result}")


if __name__ == "__main__":
    asyncio.run(main())
```

**Validation Criteria**:
- [ ] Script runs without errors
- [ ] MCP server starts automatically
- [ ] Browser opens and navigates
- [ ] Agent returns the page title
- [ ] ResultMessage contains success info

---

### Phase 1: Core Infrastructure

#### 1.1 Add Harness Abstraction

**File: `src/zoo_eval/models.py`**

Add enum for harness selection (after existing enums):

```python
class AgentHarness(str, Enum):
    """Agent execution harness."""
    BROWSER_USE = "browser_use"
    CLAUDE_SDK = "claude_sdk"
```

Update `RunConfig` to include harness selection and Claude-specific options:

```python
@dataclass
class RunConfig:
    """Configuration for task runs."""

    max_steps: int = 30
    timeout_seconds: float = 120.0
    headless: bool = True
    save_traces: bool = True
    trace_dir: str = "./traces"
    model: str = "google/gemini-2.5-flash-lite"
    shared_browser: bool = False
    autonomy_levels: list[str] = field(default_factory=lambda: ["L1"])
    completed_pairs: set[tuple[int, str]] = field(default_factory=set)
    # New fields
    harness: AgentHarness = AgentHarness.BROWSER_USE
    claude_model: str = "sonnet"  # "opus", "sonnet", or "haiku"
```

#### 1.2 Create Base Agent Runner

**File: `src/zoo_eval/base_agent_runner.py`** (new file)

Extract shared logic from `MultiAgentRunner` into abstract base class:

```python
"""Base class for agent runners with shared infrastructure."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from .models import (
    AgentConfig,
    AgentResult,
    RunConfig,
    Task,
    TaskAgentConfig,
    TaskResult,
    Universe,
)
from .scenes import SceneManager

if TYPE_CHECKING:
    from .zoo import Zoo


class BaseAgentRunner(ABC):
    """Abstract base class for agent runners."""

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

    @abstractmethod
    async def setup(self) -> None:
        """Initialize runner-specific resources."""
        pass

    @abstractmethod
    async def teardown(self) -> None:
        """Clean up runner-specific resources."""
        pass

    @abstractmethod
    async def _run_single_agent(
        self,
        agent_config: TaskAgentConfig,
        task: Task,
        start_url: str,
        autonomy_level: str = "L1",
    ) -> AgentResult:
        """Run a single agent - implementation specific."""
        pass

    def _get_universe_agent(self, agent_name: str) -> AgentConfig | None:
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

        context = f"You are {agent_config.name}"
        if universe_agent and universe_agent.role:
            context += f", a {universe_agent.role}"
        context += "."

        if universe_agent and universe_agent.persona:
            context += f" {universe_agent.persona}"

        if universe_agent and universe_agent.goal:
            context += f" Your goal: {universe_agent.goal}"

        if self.universe and self.universe.sites:
            context += f"\nYou can access: {', '.join(self.universe.sites)}"

        return context

    def _build_login_hint(self, agent_config: TaskAgentConfig) -> str:
        """Build login hint from agent's credentials."""
        if agent_config.require_login and agent_config.username and agent_config.password:
            return f"Login with username '{agent_config.username}' and password '{agent_config.password}'. "
        return ""

    def _get_agent_role(self, agent_config: TaskAgentConfig) -> str:
        """Get the role for an agent from universe config."""
        universe_agent = self._get_universe_agent(agent_config.name)
        return universe_agent.role if universe_agent else ""

    async def run_multi_agent_tasks(self, tasks: list[Task]) -> list[TaskResult]:
        """Run tasks with their defined agents."""
        # Collect all sites needed by tasks
        services = []
        if self.universe:
            all_sites = set()
            for task in tasks:
                all_sites.update(task.sites)
            services = self.universe.get_services_for_sites(list(all_sites))

        # Restart only needed services
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

            # Activate scene once per task
            scene_manager = None
            if task.scene_name:
                scene_manager = SceneManager(self.zoo, self.universe_path)
                await scene_manager.load_and_activate_scene(task.scene_name, task_start_time)

            try:
                agents = list(task.agents.values())

                for autonomy_level in self.config.autonomy_levels:
                    if (task.task_id, autonomy_level) in self.config.completed_pairs:
                        print(f"  Skipping task {task.task_id} {autonomy_level} (already completed)")
                        continue

                    result = await self._run_task_at_level(
                        task, agents, start_url, autonomy_level, scene_manager
                    )
                    all_results.append(result)

            finally:
                if scene_manager:
                    try:
                        await scene_manager.cleanup()
                    except Exception:
                        pass

        return all_results

    @abstractmethod
    async def _run_task_at_level(
        self,
        task: Task,
        agents: list[TaskAgentConfig],
        start_url: str,
        autonomy_level: str,
        scene_manager: SceneManager | None,
    ) -> TaskResult:
        """Run all agents for a task at a specific autonomy level."""
        pass

    def _aggregate_results(
        self,
        task: Task,
        agent_results: list[AgentResult],
        autonomy_level: str,
        scene_manager: SceneManager | None = None,
    ) -> TaskResult:
        """Aggregate individual agent results into a TaskResult."""
        all_succeeded = all(r.success for r in agent_results)
        combined_answer = "\n\n".join(
            f"[{r.agent_name}]: {r.answer}" for r in agent_results if r.answer
        )
        total_steps = sum(r.steps for r in agent_results)
        total_duration = sum(r.duration_seconds for r in agent_results)
        last_result = agent_results[-1] if agent_results else None

        return TaskResult(
            task_id=task.task_id,
            success=all_succeeded,
            agent_results=agent_results,
            agent_answer=combined_answer if combined_answer else None,
            final_url=last_result.final_url if last_result else None,
            page_content=last_result.page_content if last_result else None,
            steps=total_steps,
            duration_seconds=total_duration,
            raw_result=last_result.raw_result if last_result else None,
            autonomy_level=autonomy_level,
            scene_manager=scene_manager,
            scene_name=task.scene_name,
        )
```

---

### Phase 2: Refactor Existing Runner

Update `MultiAgentRunner` to extend `BaseAgentRunner`. This requires careful extraction of shared logic.

**Methods to MOVE to `BaseAgentRunner`:**
- `_get_universe_agent()` (lines 31-38)
- `_build_agent_context()` (lines 40-64)
- `run_multi_agent_tasks()` (lines 388-484) - most of it, minus browser-specific parts

**Methods to KEEP in `MultiAgentRunner`:**
- `_create_llm()` - browser-use specific LLM creation
- `_create_browser()` - Playwright browser creation
- `_run_single_agent()` - browser-use Agent execution
- `_run_shared_browser_task()` - shared browser mode logic

**Changes to `MultiAgentRunner`:**

```python
# Before
class MultiAgentRunner:
    def __init__(self, zoo, config, universe_path, universe):
        self.zoo = zoo
        self.config = config or RunConfig()
        # ...

# After
from .base_agent_runner import BaseAgentRunner

class MultiAgentRunner(BaseAgentRunner):
    def __init__(self, zoo, config, universe_path, universe):
        super().__init__(zoo, config, universe_path, universe)
        self._llm = None

    # Remove: _get_universe_agent (now in base)
    # Remove: _build_agent_context (now in base)
    # Keep: _create_llm, _create_browser, _run_single_agent, etc.
```

**Validation:**
- [ ] All existing tests pass after refactor
- [ ] `zoo-eval run` works identically to before
- [ ] No behavior changes

---

### Phase 3: Claude SDK Runner

**File: `src/zoo_eval/claude_sdk_runner.py`** (new file)

This is the key new file - much simpler than the manual approach since the SDK handles everything:

```python
"""Claude Agent SDK based runner with playwright-mcp."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from .base_agent_runner import BaseAgentRunner
from .models import AgentResult, RunConfig, Task, TaskAgentConfig, TaskResult, Universe
from .scenes import SceneManager
from .zoo import Zoo


class ClaudeSDKRunner(BaseAgentRunner):
    """Runs tasks using Claude Agent SDK with playwright-mcp."""

    def __init__(
        self,
        zoo: Zoo,
        config: RunConfig | None = None,
        universe_path: Path | None = None,
        universe: Universe | None = None,
    ):
        super().__init__(zoo, config, universe_path, universe)
        self._mcp_config = None

    async def setup(self) -> None:
        """Configure MCP server settings."""
        # Build playwright-mcp config for the Zoo environment
        browser_args = [
            "@playwright/mcp@latest",
            "--browser", "firefox",
        ]

        # Add proxy if configured (required for .zoo domain resolution)
        if self.zoo.config.proxy_url:
            browser_args.extend(["--proxy-server", self.zoo.config.proxy_url])

        # Handle self-signed certs in Zoo
        browser_args.append("--ignore-https-errors")

        self._mcp_config = {
            "zoo-playwright": {
                "command": "npx",
                "args": browser_args,
            }
        }

    async def teardown(self) -> None:
        """Clean up - SDK handles MCP server lifecycle automatically."""
        pass

    async def _run_single_agent(
        self,
        agent_config: TaskAgentConfig,
        task: Task,
        start_url: str,
        autonomy_level: str = "L1",
    ) -> AgentResult:
        """Run a single agent using Claude Agent SDK."""
        start_time = time.time()
        steps = 0
        final_url = None
        page_content = None
        messages_log = []

        try:
            # Build the prompt
            agent_context = self._build_agent_context(agent_config)
            login_hint = self._build_login_hint(agent_config)
            task_instruction = agent_config.autonomy_levels.get(autonomy_level, task.intent)

            prompt = (
                f"{agent_context}\n\n"
                f"Navigate to {start_url}. {login_hint}{task_instruction}\n\n"
                "Use the browser tools to complete this task. "
                "When done, provide your final answer."
            )

            # Configure the agent
            options = ClaudeAgentOptions(
                mcp_servers=self._mcp_config,
                allowed_tools=["mcp__zoo-playwright__*"],
                model=self.config.claude_model,
                max_turns=self.config.max_steps,
            )

            # Run the agent with proper timeout enforcement
            final_answer = None
            result_message = None

            try:
                async with asyncio.timeout(self.config.timeout_seconds):
                    async for message in query(prompt=prompt, options=options):
                        if isinstance(message, AssistantMessage):
                            messages_log.append(message)
                            for block in message.content:
                                if isinstance(block, ToolUseBlock):
                                    steps += 1
                                    # Track URL from navigate calls
                                    if block.name == "mcp__zoo-playwright__browser_navigate":
                                        final_url = block.input.get("url")
                                    # Capture page content from snapshot calls
                                    if block.name == "mcp__zoo-playwright__browser_snapshot":
                                        # The snapshot result will be in the next tool result
                                        pass

                        elif isinstance(message, ResultMessage):
                            result_message = message
                            final_answer = message.result
                            break

            except asyncio.TimeoutError:
                return AgentResult(
                    agent_name=agent_config.name,
                    agent_role=self._get_agent_role(agent_config),
                    success=False,
                    error=f"Timeout after {self.config.timeout_seconds}s",
                    steps=steps,
                    duration_seconds=time.time() - start_time,
                )

            # Capture final page content for PROGRAM_HTML evaluation
            # This requires a follow-up query to get the page state
            if steps > 0 and page_content is None:
                page_content = await self._capture_page_content(options)

            return AgentResult(
                agent_name=agent_config.name,
                agent_role=self._get_agent_role(agent_config),
                success=result_message is not None and not result_message.is_error,
                answer=final_answer,
                final_url=final_url,
                page_content=page_content,
                steps=steps,
                duration_seconds=time.time() - start_time,
                raw_result={
                    "messages": messages_log,
                    "result_message": result_message,
                    "cost_usd": result_message.total_cost_usd if result_message else None,
                },
            )

        except Exception as e:
            return AgentResult(
                agent_name=agent_config.name,
                agent_role=self._get_agent_role(agent_config),
                success=False,
                error=str(e),
                steps=steps,
                duration_seconds=time.time() - start_time,
            )

    async def _capture_page_content(self, options: ClaudeAgentOptions) -> str | None:
        """Capture current page content via browser_snapshot for evaluation."""
        try:
            async with asyncio.timeout(30):  # Short timeout for snapshot
                async for message in query(
                    prompt="Use browser_snapshot to capture the current page state. Return only the snapshot.",
                    options=options,
                ):
                    if isinstance(message, ResultMessage):
                        return message.result
        except (asyncio.TimeoutError, Exception):
            pass
        return None

    async def _run_task_at_level(
        self,
        task: Task,
        agents: list[TaskAgentConfig],
        start_url: str,
        autonomy_level: str,
        scene_manager: SceneManager | None,
    ) -> TaskResult:
        """Run agents at autonomy level - sequential for shared browser."""
        agent_results = []

        for agent_config in agents:
            result = await self._run_single_agent(
                agent_config, task, start_url, autonomy_level
            )
            agent_results.append(result)

        return self._aggregate_results(
            task, agent_results, autonomy_level, scene_manager
        )
```

**Key Simplifications vs Manual Approach**:
- No `MCPServerManager` class needed - SDK handles MCP lifecycle
- No manual agentic loop - just iterate over `query()` results
- No tool execution logic - SDK does it automatically
- No message formatting - SDK handles Anthropic API format
- Cost tracking comes free via `ResultMessage`

**Critical Implementation Details**:
- **Timeout**: Uses `asyncio.timeout()` to enforce timeout during the query loop (not after)
- **Page capture**: Adds `_capture_page_content()` method for `PROGRAM_HTML` evaluation compatibility
- **Proxy handling**: Conditionally adds `--proxy-server` flag for Zoo environment

---

### Phase 4: Runner Integration

#### 4.1 Update Task Runner

**File: `src/zoo_eval/runner.py`**

```python
from .models import AgentHarness, RunConfig, Universe
from .multi_agent_runner import MultiAgentRunner
from .zoo import Zoo


def create_agent_runner(
    zoo: Zoo,
    config: RunConfig,
    universe_path: Path | None = None,
    universe: Universe | None = None,
):
    """Factory function to create the appropriate agent runner."""
    if config.harness == AgentHarness.CLAUDE_SDK:
        from .claude_sdk_runner import ClaudeSDKRunner
        return ClaudeSDKRunner(zoo, config, universe_path, universe)
    else:
        return MultiAgentRunner(zoo, config, universe_path, universe)
```

#### 4.2 Update CLI

**File: `src/zoo_eval/cli.py`**

```python
@click.option(
    "--harness",
    type=click.Choice(["browser_use", "claude_sdk"]),
    default="browser_use",
    help="Agent harness to use",
)
@click.option(
    "--claude-model",
    type=click.Choice(["opus", "sonnet", "haiku"]),
    default="sonnet",
    help="Claude model for claude_sdk harness",
)
def run(universe, task, harness, claude_model, ...):
    """Run evaluation tasks."""

    # Validate environment for Claude SDK
    if harness == "claude_sdk":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise click.ClickException(
                "ANTHROPIC_API_KEY environment variable required for claude_sdk harness"
            )

    config = RunConfig(
        harness=AgentHarness(harness),
        claude_model=claude_model,
        ...
    )
```

---

### Phase 5: Testing & Validation

#### 5.1 Unit Tests

**File: `tests/test_claude_sdk_runner.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoo_eval.claude_sdk_runner import ClaudeSDKRunner
from zoo_eval.models import AgentConfig, AgentHarness, RunConfig, TaskAgentConfig, Universe


@pytest.fixture
def mock_zoo():
    zoo = MagicMock()
    zoo.config.proxy_url = "localhost:3128"
    zoo.resolve_url.return_value = "https://example.zoo"
    return zoo


@pytest.fixture
def config():
    return RunConfig(
        harness=AgentHarness.CLAUDE_SDK,
        claude_model="sonnet",
        max_steps=10,
    )


@pytest.fixture
def universe():
    return Universe(
        name="test",
        sites=["example.zoo"],
        agents=[AgentConfig(role="tester", name="alice", persona="Test user", goal="Complete tasks")],
        services={},
    )


class TestClaudeSDKRunner:
    def test_build_agent_context(self, mock_zoo, config, universe):
        runner = ClaudeSDKRunner(mock_zoo, config, universe=universe)
        agent_config = TaskAgentConfig(name="alice")
        context = runner._build_agent_context(agent_config)

        assert "You are alice" in context
        assert "tester" in context

    def test_build_login_hint(self, mock_zoo, config):
        runner = ClaudeSDKRunner(mock_zoo, config)
        agent_config = TaskAgentConfig(
            name="alice", require_login=True, username="alice", password="secret"
        )
        hint = runner._build_login_hint(agent_config)

        assert "alice" in hint
        assert "secret" in hint

    async def test_setup_creates_mcp_config(self, mock_zoo, config):
        runner = ClaudeSDKRunner(mock_zoo, config)
        await runner.setup()

        assert runner._mcp_config is not None
        assert "zoo-playwright" in runner._mcp_config
        assert "npx" in runner._mcp_config["zoo-playwright"]["command"]
```

#### 5.2 Integration Tests

```python
@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="No API key")
async def test_simple_navigation(zoo_fixture):
    """Test Claude SDK can navigate to a page."""
    config = RunConfig(harness=AgentHarness.CLAUDE_SDK, max_steps=5)
    runner = ClaudeSDKRunner(zoo_fixture, config)

    await runner.setup()
    try:
        result = await runner._run_single_agent(
            TaskAgentConfig(name="alice", autonomy_levels={"L1": "Read the page title"}),
            task=...,
            start_url="https://example.zoo",
            autonomy_level="L1",
        )
        assert result.success
    finally:
        await runner.teardown()
```

#### 5.3 Comparative Benchmark

**File: `scripts/compare_harnesses.py`**

```python
"""Compare browser-use and Claude SDK harnesses on the same tasks."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from zoo_eval.models import AgentHarness, RunConfig, load_tasks, load_universe
from zoo_eval.runner import create_agent_runner
from zoo_eval.zoo import Zoo


async def run_comparison(universe_name: str, task_file: str):
    """Run same tasks with both harnesses and compare."""
    universe_path = Path(f"pet_to_wild/universes/{universe_name}")
    universe = load_universe(universe_path)
    tasks = load_tasks(Path(task_file))
    zoo = Zoo()

    results = {}

    for harness_name in ["browser_use", "claude_sdk"]:
        config = RunConfig(
            harness=AgentHarness(harness_name),
            max_steps=20,
            autonomy_levels=["L1"],
        )

        runner = create_agent_runner(zoo, config, universe_path, universe)
        await runner.setup()

        try:
            task_results = await runner.run_multi_agent_tasks(tasks)
            results[harness_name] = [
                {
                    "task_id": r.task_id,
                    "success": r.success,
                    "steps": r.steps,
                    "duration": r.duration_seconds,
                }
                for r in task_results
            ]
        finally:
            await runner.teardown()

    # Print comparison
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(run_comparison("startup", "pet_to_wild/universes/startup/tasks/simple_navigation.yaml"))
```

---

## Implementation Checklist

### Pre-Phase: SDK Verification
- [ ] Install `claude-agent-sdk` package
- [ ] Verify imports work (`query`, `ClaudeAgentOptions`, etc.)
- [ ] Document any API differences from plan
- [ ] **Decision gate**: Proceed or use fallback plan

### Phase 0: Proof of Concept
- [ ] Create `scripts/poc_claude_sdk.py`
- [ ] Test with playwright-mcp server
- [ ] Verify proxy connectivity (`--proxy-server` flag works)
- [ ] Verify cert handling (`--ignore-https-errors` flag works)
- [ ] Confirm browser automation succeeds
- [ ] Measure MCP server startup time
- [ ] Note any API quirks

### Phase 1: Core Infrastructure
- [ ] Add `AgentHarness` enum to `models.py`
- [ ] Add `claude_model` field to `RunConfig`
- [ ] Create `base_agent_runner.py` with shared logic

### Phase 2: Refactor Existing Runner
- [ ] Move `_get_universe_agent()` to base class
- [ ] Move `_build_agent_context()` to base class
- [ ] Move `run_multi_agent_tasks()` to base class
- [ ] Update `MultiAgentRunner` to extend `BaseAgentRunner`
- [ ] Remove duplicated methods from `MultiAgentRunner`
- [ ] Ensure all existing tests pass
- [ ] Verify `zoo-eval run` works identically

### Phase 3: Claude SDK Runner
- [ ] Create `claude_sdk_runner.py`
- [ ] Implement `setup()` with MCP config
- [ ] Implement `_run_single_agent()` using `query()`
- [ ] Add `asyncio.timeout()` wrapper for timeout enforcement
- [ ] Implement `_capture_page_content()` for evaluation
- [ ] Handle result extraction from `ResultMessage`
- [ ] Track steps via `ToolUseBlock`

### Phase 4: Integration
- [ ] Add `create_agent_runner()` factory in `runner.py`
- [ ] Update CLI with `--harness` option
- [ ] Update CLI with `--claude-model` option
- [ ] Add `ANTHROPIC_API_KEY` validation in CLI

### Phase 5: Testing
- [ ] Unit tests for `ClaudeSDKRunner`
- [ ] Unit tests for `_capture_page_content()`
- [ ] Integration tests (skip without API key)
- [ ] Test `PROGRAM_HTML` evaluation works
- [ ] Comparative benchmark script
- [ ] Document performance differences

---

## Key Differences Between Harnesses

| Aspect | browser-use | Claude Agent SDK |
|--------|-------------|------------------|
| Browser control | Direct Playwright API | MCP tool calls |
| Agentic loop | Managed by browser-use | Managed by SDK |
| LLM provider | OpenRouter (any model) | Anthropic Claude only |
| MCP lifecycle | N/A | Auto-managed by SDK |
| Step tracking | `on_step_end` hook | `ToolUseBlock` in stream |
| Page capture | CDP `getOuterHTML` | `browser_snapshot` tool |
| Cost tracking | Manual calculation | `ResultMessage.total_cost_usd` |
| Multi-agent | Concurrent or sequential | Sequential (shared MCP) |

---

## Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
claude = [
    "claude-agent-sdk>=0.1.0",
]
```

Install:
```bash
pip install -e ".[claude]"
```

---

## Environment Variables

| Variable | Required For | Description |
|----------|--------------|-------------|
| `ANTHROPIC_API_KEY` | claude_sdk harness | Anthropic API key |
| `OPENROUTER_API_KEY` | browser_use harness | OpenRouter API key |

---

## Usage Examples

```bash
# Run with browser-use (default)
zoo-eval run startup --task tasks/simple.yaml

# Run with Claude SDK
export ANTHROPIC_API_KEY=your-key
zoo-eval run startup --task tasks/simple.yaml --harness claude_sdk

# Use Claude Opus for complex tasks
zoo-eval run startup --task tasks/complex.yaml --harness claude_sdk --claude-model opus

# Compare harnesses
python scripts/compare_harnesses.py startup tasks/simple.yaml
```

---

## Future Considerations

1. **Harness tracking**: Add `harness: str` field to `TaskResult` for comparative analysis
2. **Parallel agents**: Support concurrent agents with separate MCP servers
3. **Model comparison**: Benchmark Opus vs Sonnet vs Haiku
4. **Cost budgets**: Use `max_budget_usd` option for cost control
5. **Session reuse**: Use `continue_conversation` for multi-turn tasks
6. **MCP server pooling**: Reuse MCP servers across agents to reduce startup overhead
7. **Harness-agnostic config**: Replace `claude_model` with `harness_options: dict` for extensibility
