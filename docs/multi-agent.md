# Multi-Agent Evaluation with Universes

## Overview

Zoo-eval supports multi-agent evaluation through **Universes**. A universe defines:
- Which Zoo sites are active
- What agents are available (with their personas and goals)

Tasks specify which universes they're compatible with and are automatically assigned to agents.

## Universe Configuration

Create a universe YAML file defining sites and agents:

```yaml
name: startup_universe
sites:
  - mail
  - kanban
  - gitea
  - wiki
agents:
  - role: cofounder
    name: alice
    persona: CEO and co-founder, focused on customer communication
    goal: Triage inbound emails and respond to customer inquiries

  - role: senior_engineer
    name: bob
    persona: Senior software engineer, code reviewer
    goal: Review pull requests and update documentation

  - role: junior_engineer
    name: charlie
    persona: Junior software engineer, implements features
    goal: Fix bugs from the kanban board

  - role: pm
    name: diana
    persona: Product manager, coordinates team
    goal: Update the project board with new tasks
```

### Fields

**Universe:**
- `name`: Unique identifier for the universe
- `sites`: List of Zoo sites to activate
- `agents`: List of agent configurations

**Agent:**
- `role`: Agent's role identifier
- `name`: Agent's name (should match Zoo credentials)
- `persona`: Description of agent's character/behavior
- `goal`: Individual agent's goal/objective

## Task Configuration

Tasks specify their intent, which agent runs them, and compatible universes:

```yaml
tasks:
- id: 1
  agent: alice  # Required: which agent runs this task
  intent: Tell me what the main heading says
  start_url: https://home.zoo
  compatible_universes:
    - startup_universe
  require_login: false
  require_reset: false
  eval:
    types:
    - string_match
    answers:
      must_include:
      - home

- id: 2
  agent: bob  # This task runs as Bob
  intent: Navigate to https://auth.zoo and tell me what you see
  start_url: https://home.zoo
  compatible_universes:
    - startup_universe

- id: 3
  agent: diana  # This task runs as Diana
  intent: Send an email to the team
  start_url: https://snappymail.zoo
  compatible_universes:
    - startup_universe
  require_login: true
  username: diana@snappymail.zoo
  password: diana123
```

## Task Assignment

Each task must specify an `agent` field that matches an agent's `name` from the universe config:

```yaml
# In task file:
- id: 103
  agent: diana  # Matches agent name in universe

# In universe config:
agents:
  - role: pm
    name: diana  # This agent will run task 103
    persona: Product manager
```

The agent name matching is **case-insensitive** (e.g., `agent: Diana` matches `name: diana`).

### Validation

- Tasks without an `agent` field will print an error and be skipped
- Tasks with an unknown agent name will print an error and be skipped

## Execution Modes

### Separate Browser Mode (Default)

```bash
uv run zoo-eval run configs/tasks.yaml --universe universes/startup_universe.yaml --model gpt-4o
```

- Each agent gets its own browser instance
- Agents run **concurrently**
- No shared memory between agents
- Coordinate only through Zoo environment (emails, kanban, etc.)

### Shared Browser Mode

```bash
uv run zoo-eval run configs/tasks.yaml --universe universes/startup_universe.yaml --model gpt-4o --shared-browser
```

- All agents share **one browser instance**
- Agents run **sequentially**
- Shared memory and context
- Later agents see earlier agents' actions

## Results

Each agent produces an `AgentResult` with:
- `agent_name`, `agent_role`
- `success`, `error`
- `answer`, `final_url`, `page_content`
- `steps`, `duration_seconds`

Task success requires all assigned agents to succeed.

## Default Universes

### startup_universe

Four agents collaborate on startup workflow tasks:
- **alice** (cofounder): Triage inbound emails
- **bob** (senior_engineer): Review pull requests and update docs
- **charlie** (junior_engineer): Fix bugs from kanban board
- **diana** (pm): Update project board

**Sites:** mail, kanban, gitea, wiki

## Usage Examples

Run 3 simple tasks:
```bash
uv run zoo-eval run configs/test_simple.yaml --universe universes/startup_universe.yaml --model gpt-4o
```

Watch in browser (non-headless):
```bash
uv run zoo-eval run configs/test_simple.yaml --universe universes/startup_universe.yaml --model gpt-4o --no-headless
```

Shared browser mode with shorter timeout:
```bash
uv run zoo-eval run configs/test_simple.yaml --universe universes/startup_universe.yaml --model gpt-4o --shared-browser --timeout 60
```
