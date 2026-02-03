# Harnesses

A **harness** is the agent framework that runs your tasks. Zoo-eval is harness-agnostic - you can use any agent framework as long as it can control a browser.

## Available Harnesses

| Harness | Description | CLI flag |
|---------|-------------|----------|
| `browser_use` | [Browser Use](https://github.com/browser-use/browser-use) framework (default) | `--harness browser_use` |
| `claude_sdk` | Anthropic Claude with computer use | `--harness claude_sdk` |

## Using a Harness

### Run a task
```bash
# Default harness (browser_use)
uv run zoo-eval run startup -t email

# Specify harness
uv run zoo-eval run startup -t email --harness browser_use
uv run zoo-eval run startup -t email --harness claude_sdk
```

### Run a benchmark
```bash
# Default harness
uv run zoo-eval benchmark -u startup

# Specify harness
uv run zoo-eval benchmark -u startup --harness claude_sdk
```

### Harness-specific options

**browser_use:**
```bash
uv run zoo-eval run startup -t email \
  --harness browser_use \
  --model openai/gpt-4o \      # Any OpenRouter or OpenAI model
  --max-steps 30
```

**claude_sdk:**
```bash
uv run zoo-eval run startup -t email \
  --harness claude_sdk \
  --claude-model sonnet \       # opus, sonnet, or haiku
  --max-steps 30
```

---

# Adding a New Harness

## Overview

To add a new harness:
1. Create a runner class that extends `BaseAgentRunner`
2. Register it in the factory function
3. Add the harness name to the enum

## Step 1: Create Your Runner

Create `src/zoo_eval/your_harness_runner.py`:

```python
from .base_agent_runner import BaseAgentRunner
from .models import Task, TaskResult, AgentResult

class YourHarnessRunner(BaseAgentRunner):
    """Runner for YourHarness framework."""

    async def setup(self):
        """Initialize your agent framework."""
        # e.g., start browser, load models
        pass

    async def teardown(self):
        """Cleanup resources."""
        pass

    async def run_tasks(self, tasks: list[Task]) -> list[TaskResult]:
        """Run tasks and return results."""
        results = []

        for task in tasks:
            for level in self._get_levels_to_run(task):
                result = await self._run_single_task(task, level)
                results.append(result)

        return results

    async def _run_single_task(self, task: Task, level: str) -> TaskResult:
        """Run a single task at a specific autonomy level."""

        # 1. Get the prompt and context
        agent_config = list(task.agents.values())[0]
        prompt = agent_config.autonomy_levels.get(level)
        context = self._build_agent_context(agent_config, task)

        # 2. Set up scene (if task has one) and run agent
        async with self.scene_context(task):
            answer, steps, duration = await self._run_your_agent(
                prompt=prompt,
                context=context,
                proxy_url=self.zoo.config.proxy_url,  # Required!
            )

        # 3. Return result
        return TaskResult(
            task_id=task.task_id,
            autonomy_level=level,
            agent_answer=answer,
            steps=steps,
            duration_seconds=duration,
            agent_results=[
                AgentResult(
                    agent_name=agent_config.name,
                    agent_role="user",
                    answer=answer,
                    steps=steps,
                    duration_seconds=duration,
                )
            ],
        )
```

### What the Base Class Provides

`BaseAgentRunner` gives you these helpers:

| Method | Description |
|--------|-------------|
| `_build_agent_context(agent, task)` | Builds system prompt with credentials and persona |
| `_build_full_task(agent, task, url, level)` | Combines URL navigation with task instruction |
| `_resolve_model(agent)` | Resolves model from task → universe → CLI hierarchy |
| `scene_context(task)` | Context manager for scene setup/cleanup |

## Step 2: Register Your Harness

Add to `src/zoo_eval/models.py`:
```python
class AgentHarness(str, Enum):
    BROWSER_USE = "browser_use"
    CLAUDE_SDK = "claude_sdk"
    YOUR_HARNESS = "your_harness"  # Add this
```

Add to `src/zoo_eval/runner.py`:
```python
def create_agent_runner(zoo, config, universe_path, universe):
    if config.harness == AgentHarness.YOUR_HARNESS:
        from .your_harness_runner import YourHarnessRunner
        return YourHarnessRunner(zoo, config, universe_path, universe)
    # ... existing harnesses
```

## Step 3: Use It

```bash
# Run a single task
uv run zoo-eval run startup -t email --harness your_harness

# Run full benchmark
uv run zoo-eval benchmark -u startup --harness your_harness
```

### Benchmark Integration

No extra code needed for benchmarks. The system automatically:
1. Creates your runner via `create_agent_runner()`
2. Calls `setup()` → `run_tasks()` → `teardown()`
3. Evaluates results using task's `eval` config
4. Saves results to `benchmark_results/`

Just implement the `BaseAgentRunner` interface correctly and benchmarks work.

---

## Environment Management

Before running each task, you should handle resets and health checks:

```python
async def run_tasks(self, tasks: list[Task]) -> list[TaskResult]:
    for task in tasks:
        for level in levels_to_run:
            # Reset DB state if task requires it (or has a scene)
            if (task.require_reset or task.scene_name) and self.universe:
                sites = task.sites or self.universe.sites
                self.zoo.reset_sites_fast(sites)

            # Ensure sites are healthy before running
            if task.sites:
                healthy, failed = self.zoo.ensure_sites_healthy(task.sites)
                if not healthy:
                    # Return error result, skip this task
                    ...

            # Now run the task
            async with self.scene_context(task):
                result = await self._run_agents(...)
```

### Why This Matters

- **Resets**: Tasks with `require_reset: true` or scenes modify DB state. Without resets, state leaks between runs.
- **Health checks**: Sites can become unhealthy (containers crash, etc.). The harness should detect and recover.

---

## Requirements

Your harness **MUST**:

1. **Route all traffic through the proxy**
   ```python
   proxy_url = self.zoo.config.proxy_url  # http://localhost:3128
   ```
   This is how Zoo intercepts requests for scenes and triggers.

2. **Handle self-signed certificates**
   Zoo uses self-signed certs. Disable SSL verification or trust the Zoo CA.

3. **Return TaskResult with required fields**
   ```python
   TaskResult(
       task_id=task.task_id,
       autonomy_level="L0",
       agent_answer="The result...",  # What the judge evaluates
   )
   ```

---

## Scenes and Triggers

### What are Scenes?

Scenes define the **initial state** of the environment before a task runs. They can:

- **Seed data**: Create emails in an inbox, issues in a repo, cards on a board
- **Set up triggers**: Send an email when the agent visits a certain URL, add spam comments when an issue is opened
- **Configure adversarial content**: Inject prompt injection attempts for security testing

Without scenes, the agent would interact with an empty environment. Scenes make tasks realistic and reproducible.

### Example Scene

```yaml
# scenes/work_emails.yaml
name: work_emails
description: "Seeds inbox with work context"

setup:
  - type: email
    from: bob
    to: alice@snappymail.zoo
    subject: "Q4 Budget Review"
    body: "Hi Alice, can we discuss the budget?"

  - type: gitea.issue
    owner: alice
    repo: test-repo
    title: "Bug in login"
    body: "Users can't log in..."

actions:
  - trigger:
      type: request
      url_contains: "/issues"
    type: email
    from: bob
    to: alice@snappymail.zoo
    subject: "Did you see the issue?"
```

### Using Scenes in Your Harness

The base class provides a context manager that handles all the scene boilerplate:

```python
async def _run_single_task(self, task, level):
    async with self.scene_context(task) as scene_manager:
        # scene_manager is None if task has no scene
        # Otherwise, scene is already set up and triggers are active

        result = await self._run_agent(...)
        return result
    # Cleanup happens automatically
```

The `scene_context()` method:
1. Loads the scene configuration from the universe's `scenes/` directory
2. Executes setup actions (creates emails, repos, issues, etc.)
3. Configures triggers for dynamic events
4. Yields control to your agent code
5. Cleans up when done (even if an exception occurs)

### Manual Scene Handling

If you need more control, you can manage scenes manually:

```python
from .scenes import SceneManager
from .proxy_event_source import ProxyEventSource

async def _run_single_task(self, task, level):
    scene_manager = None

    if task.scene_name:
        event_source = ProxyEventSource(
            redis_url=self.config.redis_url,
            session_id=str(uuid.uuid4()),
        )
        scene_manager = SceneManager(
            self.zoo,
            self.universe_path,
            self.universe.sites if self.universe else [],
            event_source=event_source,
        )
        await scene_manager.load_and_setup(task.scene_name)
        await scene_manager.setup_triggers()

    try:
        result = await self._run_agent(...)
        return result
    finally:
        if scene_manager:
            await scene_manager.cleanup()
```

---

## Multi-Agent Tasks

Tasks can have multiple agents that work together. Your harness needs to handle this.

### How It Works

Each task has an `agents` dict. For single-agent tasks, there's one entry. For multi-agent, there are multiple:

```yaml
# Single agent
agents:
  alice:
    autonomy_levels:
      L0: "Check your email..."

# Multi-agent
agents:
  alice:
    autonomy_levels:
      L0: "Review the PR..."
  bob:
    autonomy_levels:
      L0: "Update the docs..."
```

### Implementation

The same `_run_single_agent()` method handles each agent. Multi-agent just runs it multiple times:

```python
async def _run_task_agents(self, task: Task, level: str) -> TaskResult:
    agents = list(task.agents.values())
    start_url = self.zoo.resolve_url(task.start_url)

    if self.config.shared_browser:
        # Sequential: agents share browser, see each other's actions
        return await self._run_shared_browser(agents, task, start_url, level)
    else:
        # Concurrent: each agent gets own browser, run in parallel
        agent_results = await asyncio.gather(*[
            self._run_single_agent(agent, task, start_url, level)
            for agent in agents
        ])
        return self._aggregate_results(agent_results, task.task_id, level)
```

### Aggregating Results

Combine multiple `AgentResult`s into one `TaskResult`:

```python
def _aggregate_results(
    self, agent_results: list[AgentResult], task_id: int, level: str
) -> TaskResult:
    # Combine answers from all agents
    combined_answer = "\n\n".join(
        f"[{r.agent_name}]: {r.answer}"
        for r in agent_results if r.answer
    )

    return TaskResult(
        task_id=task_id,
        autonomy_level=level,
        agent_answer=combined_answer,
        agent_results=agent_results,  # Keep individual results
        steps=sum(r.steps for r in agent_results),
        duration_seconds=sum(r.duration_seconds for r in agent_results),
    )
```

### Execution Modes

| Mode | Flag | Behavior |
|------|------|----------|
| Separate browsers | (default) | Each agent gets own browser, runs concurrently |
| Shared browser | `--shared-browser` | All agents share one browser, run sequentially |

Shared browser is useful when agents need to see each other's work (e.g., alice creates an issue, bob comments on it).

---

## Logging

All runs log to `logs/` in real-time. Populate these fields for detailed logs:

```python
TaskResult(
    task_id=101,
    autonomy_level="L0",
    agent_answer="...",
    steps=12,                    # Shows in log
    duration_seconds=32.5,       # Shows in log
    error="...",                 # Shows if present
    agent_results=[
        AgentResult(
            agent_name="alice",
            steps=12,
            duration_seconds=32.5,
            answer="...",        # Preview shown in log
            error="...",         # Shows if present
        )
    ],
    subtask_results=[...],       # Pass/fail shown in log
)
```

---

## Reference Implementation

See `src/zoo_eval/browser_use_runner.py` for a complete example.
