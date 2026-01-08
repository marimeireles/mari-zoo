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

Tasks specify their intent and compatible universes:

```yaml
tasks:
- id: 1
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
  intent: Navigate to https://auth.zoo and tell me what you see
  start_url: https://home.zoo
  compatible_universes:
    - startup_universe
```

## Task Assignment

Tasks are assigned to agents **sequentially** based on their order in the YAML:
- Task 1 → Agent 1 (alice)
- Task 2 → Agent 2 (bob)
- Task 3 → Agent 3 (charlie)
- Task 4 → Agent 4 (diana)

Each agent executes their assigned task using their individual `goal` from the universe.

### Task Overflow

When there are more tasks than agents:
- All overflow tasks are assigned to the **last agent**
- A warning is printed: "X extra task(s) assigned to last agent (name)"
- This is normal for `--shared-browser` mode

Example with 4 agents and 6 tasks:
- Task 1 → alice
- Task 2 → bob
- Task 3 → charlie
- Task 4 → diana
- Task 5 → diana (overflow)
- Task 6 → diana (overflow)

### Idle Agents

If there are more agents than tasks, remaining agents are idle.

Example with 4 agents and 2 tasks:
- Task 1 → alice
- Task 2 → bob
- charlie: idle
- diana: idle

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
