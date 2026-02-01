# Adding a New Harness

## Quick Start

1. **Create your runner** in `src/zoo_eval/your_harness_runner.py`:

```python
from .base_agent_runner import BaseAgentRunner
from .proxy_event_source import ProxyEventSource
from .scenes import SceneManager

class YourHarnessRunner(BaseAgentRunner):
    async def run_tasks(self, tasks):
        results = []
        for task in tasks:
            # Set up scene triggers if task has a scene
            scene_manager = None
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
                # Run your agent with proxy configured
                result = await self._run_agent(
                    task,
                    proxy_url=self.zoo.config.proxy_url,  # Required!
                )
                results.append(result)
            finally:
                if scene_manager:
                    await scene_manager.cleanup()

        return results
```

2. **Register it** in `src/zoo_eval/runner.py`:

```python
from .models import AgentHarness

# Add to AgentHarness enum in models.py:
YOUR_HARNESS = "your_harness"

# Add to create_agent_runner():
if config.harness == AgentHarness.YOUR_HARNESS:
    from .your_harness_runner import YourHarnessRunner
    return YourHarnessRunner(zoo, config, universe_path, universe)
```

3. **Add CLI option** in `src/zoo_eval/cli.py` (already supports any harness value).

## Requirements

Your harness MUST:
- Route all HTTP traffic through `zoo.config.proxy_url` (default: `http://localhost:3128`)
- Handle SSL/TLS (zoo uses self-signed certs, use `verify=False` or equivalent)
- Use `_build_agent_context(agent_config, task)` to include credentials and sensitive data in agent context

## API Reference

### ProxyEventSource
```python
from zoo_eval.proxy_event_source import ProxyEventSource

event_source = ProxyEventSource(
    redis_url="redis://localhost:6379",
    session_id="optional-for-filtering",  # Filters events by X-Zoo-Session header
)
await event_source.start()
# ... use with SceneManager ...
await event_source.stop()
```

### SceneManager
```python
from zoo_eval.scenes import SceneManager

scene_manager = SceneManager(
    zoo=zoo,
    universe_path=Path("pet_to_wild/universes/startup"),
    event_source=event_source,  # Required for request triggers
)
await scene_manager.load_and_setup("scene_name")  # Runs setup scripts
await scene_manager.setup_triggers()               # Activates triggers
# ... run agent ...
await scene_manager.cleanup()
```

### BaseAgentRunner
```python
from zoo_eval.base_agent_runner import BaseAgentRunner

class YourRunner(BaseAgentRunner):
    async def setup(self): ...      # Called before running tasks
    async def teardown(self): ...   # Called after all tasks
    async def run_tasks(self, tasks) -> list[TaskResult]: ...  # Main entry point
```

## Trigger Types

| Type | Description | Needs EventSource |
|------|-------------|-------------------|
| `request` | Fires on HTTP request matching URL pattern | Yes |
| `poll` | Polls endpoint until condition met | No |
| `time` | Fires after delay (seconds) | No |
| `page_load` | Fires immediately | No |

## Evaluation System

Your harness returns `TaskResult` → generic LLM judge evaluates it.

**Required fields:**
```python
TaskResult(
    task_id=task.task_id,
    agent_answer="Final output text",    # What judge evaluates
    autonomy_level="L1",
)
```

**Optional fields for better evaluation:**
```python
TaskResult(
    agent_results=[AgentResult(...)],    # Per-agent details (multi-agent)
    final_url="https://...",              # Last URL
    page_content="<html>...</html>",      # Final page HTML
    steps=42,                             # Action count
    duration_seconds=120.5,
    raw_result=your_result,               # If has agent_steps() method, judge uses it
)
```

**Judge sees:** `agent_answer` + step descriptions (if `raw_result.agent_steps()` exists)
**Judge doesn't see:** Screenshots, tool calls, internal state

## File Structure

```
src/zoo_eval/
├── base_agent_runner.py    # Extend this
├── evaluators.py           # LLM judge (harness-agnostic)
├── models.py               # TaskResult, AgentResult
├── browser_use_runner.py   # Reference implementation
└── your_harness_runner.py  # Your harness
```
