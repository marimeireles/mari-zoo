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

        # 1. Get the prompt for this level
        agent_config = list(task.agents.values())[0]
        prompt = agent_config.autonomy_levels.get(level)

        # 2. Build context (includes credentials, sensitive data)
        context = self._build_agent_context(agent_config, task)

        # 3. Run your agent
        # IMPORTANT: Route traffic through proxy
        answer, steps, duration = await self._run_your_agent(
            prompt=prompt,
            context=context,
            proxy_url=self.zoo.config.proxy_url,  # Required!
        )

        # 4. Return result
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
uv run zoo-eval run startup -t email --harness your_harness
```

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

If your tasks use scenes (dynamic environment setup), you need to handle the SceneManager:

```python
from .scenes import SceneManager
from .proxy_event_source import ProxyEventSource

async def _run_single_task(self, task, level):
    scene_manager = None

    # Set up scene if task has one
    if task.scene_name:
        event_source = ProxyEventSource(
            redis_url=self.config.redis_url,
            session_id=str(uuid.uuid4()),
        )
        scene_manager = SceneManager(
            self.zoo,
            self.universe_path,
            event_source=event_source,
        )
        await scene_manager.load_and_setup(task.scene_name)
        await scene_manager.setup_triggers()

    try:
        # Run your agent...
        result = await self._run_agent(...)
        return result
    finally:
        if scene_manager:
            await scene_manager.cleanup()
```

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
