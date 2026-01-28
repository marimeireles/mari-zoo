# zoo-eval

Web agent evaluation harness using [The Zoo](https://github.com/anthropics/the_zoo).

## Setup

```bash
# Install dependencies
uv sync

# Install playwright browsers
uv run playwright install chromium

# Set API keys
export OPENROUTER_API_KEY=your-key    # Required (default uses Gemini 2.5 Flash)
export OPENAI_API_KEY=your-key        # Required for LLM judge evaluation

# Optional: Override LLM judge model (default: gpt-5)
export OPENAI_JUDGE_MODEL=gpt-4o
```

## Quick Start

```bash
# Start The Zoo
npx the_zoo start

# Run a single task (runs all autonomy levels by default)
uv run zoo-eval run startup --task email --id 101

# Watch in browser (non-headless)
uv run zoo-eval run startup --task email --id 101 --no-headless
```

## Running Tasks

```bash
# Run specific task by ID
uv run zoo-eval run startup --task email --id 101

# Run multiple tasks
uv run zoo-eval run startup --task email --id 101 --id 102

# Run all tasks in a task file
uv run zoo-eval run startup --task email

# Use a different agent model
uv run zoo-eval run startup --task email --id 101 --model gpt-4o
uv run zoo-eval run startup --task email --id 101 --model claude

# Use a different LLM judge model (for evaluation)
uv run zoo-eval run startup --task email --id 101 --judge-model gpt-4o
```

## Autonomy Levels

Tasks run at all autonomy levels by default. See [Benchmark Guide](docs/benchmark_guide.md#autonomy-levels) for details.

## Other Options

```bash
# Shared browser mode (agents run sequentially with shared context)
uv run zoo-eval run startup --task email --shared-browser

# Custom timeout and max steps
uv run zoo-eval run startup --task email --id 101 --timeout 180 --max-steps 50

# Resume an interrupted run
uv run zoo-eval run startup --task email --resume
```

## Documentation

- [Benchmark Guide](docs/benchmark_guide.md) - Full task and evaluation configuration
- [Multi-Agent](docs/multi-agent.md) - Multi-agent evaluation details

## Reports

```bash
# Show latest run report
uv run zoo-eval report

# List all runs
uv run zoo-eval report --list

# Show specific run
uv run zoo-eval report 4
```

## Other Commands

```bash
# Check Zoo status
uv run zoo-eval status

# Reset databases
uv run zoo-eval reset

# Query databases directly
uv run zoo-eval postgres "SELECT * FROM users LIMIT 5" -d shopping
uv run zoo-eval mysql --list

# Audit db_match tasks (verify queries return correct expected values)
uv run python scripts/audit_db_evals.py configs/tasks.yaml
uv run python scripts/audit_db_evals.py configs/tasks.yaml --tasks 21
```

## Dynamic Database Evaluation

Use `db_match` eval type to dynamically query the database for expected values instead of hardcoding:

```yaml
- id: 21
  intent: List reviewers who mention ear cups being small
  eval:
    types:
      - db_match
    db_query:
      database: onestopshop_db
      type: mysql
      match_type: must_include
      query: |
        SELECT DISTINCT rd.nickname
        FROM review r
        JOIN review_detail rd ON r.review_id = rd.review_id
        WHERE r.entity_pk_value = 76525
        AND rd.detail LIKE '%small ear%'
```

This makes evaluations self-documenting and catches dataset bugs.
