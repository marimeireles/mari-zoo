# Multi-Agent Support

## Overview

Zoo-eval supports running multiple agents on the same task, enabling evaluation of collaborative agent scenarios.

## Task Configuration

Define multiple agents in your task YAML:

```yaml
tasks:
- id: 1001
  sites:
  - auth
  intent: Multi-agent task description
  start_url: https://home.zoo
  agents:
    - role: explorer
      name: Alice
      persona: A curious explorer who investigates services
      initial_task: Navigate to https://auth.zoo and read the heading

    - role: verifier
      name: Bob
      persona: A careful verifier who checks details
      initial_task: Stay on homepage and list available services

  require_login: false
  require_reset: false
  eval:
    types:
    - string_match
    answers:
      must_include:
      - Zoo
```

## Agent Fields

- **role**: Agent's role identifier
- **name**: Agent's name (used in prompts and results)
- **persona**: Description of agent's character/behavior
- **initial_task**: Specific task for this agent

## Execution Modes

### Separate Browser Mode (Default)

```bash
uv run zoo-eval run configs/tasks.yaml
```

- Each agent gets its own browser instance
- Agents run concurrently
- No shared memory between agents
- Coordinate only through Zoo environment

### Shared Browser Mode

```bash
uv run zoo-eval run configs/tasks.yaml --shared-browser
```

- All agents share one browser instance
- Agents run sequentially
- Shared memory and context
- Later agents see earlier agents' actions

## Results

Each agent produces an `AgentResult` with:
- `agent_name`, `agent_role`
- `success`, `error`
- `answer`, `final_url`, `page_content`
- `steps`, `duration_seconds`

Task success requires all agents to succeed.
