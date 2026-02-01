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

Tasks define agents in the `agents:` section. See [Task Reference](task_reference.md) for full task structure.

```yaml
tasks:
- id: 103
  agents:
    diana:
      require_login: true
      autonomy_levels:
        L0: "1. Send email to team..."
        L1: "Send an email to the team"
        L2: "You work at a startup as a product manager."
```

Agent names must match entries in the universe config and `credentials/*.zoo.yaml`.

## Execution Modes

### Separate Browser Mode (Default)

```bash
uv run zoo-eval run configs/tasks.yaml --universe universes/startup_universe.yaml --model gpt-5.1
```

- Each agent gets its own browser instance
- Agents run **concurrently**
- No shared memory between agents
- Coordinate only through Zoo environment (emails, kanban, etc.)

### Shared Browser Mode

```bash
uv run zoo-eval run configs/tasks.yaml --universe universes/startup_universe.yaml --model gpt-5.1 --shared-browser
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

### startup

Four agents collaborate on startup workflow tasks:
- **alice** (cofounder): Triage inbound emails
- **bob** (senior_engineer): Review pull requests and update docs
- **charlie** (junior_engineer): Fix bugs from kanban board
- **diana** (pm): Update project board

**Sites:** snappymail, focalboard, gitea

### personal_assistant

Single agent for personal task assistance:
- **emma.lopez**: Personal shopping and research assistant

**Sites:** postmill, onestopshop, wiki
