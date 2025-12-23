# zoo-eval

Web agent evaluation harness using [The Zoo](https://github.com/anthropics/the_zoo).

## Setup

```bash
# Install dependencies
uv sync

# Install playwright browsers
uv run playwright install chromium

# Set API key
export OPENROUTER_API_KEY=your-key    # Required (default uses Gemini 2.5 Flash)
export OPENAI_API_KEY=your-key        # Only needed for --model gpt-4o
```

## Running Evaluations

```bash
# Start The Zoo first
npx the_zoo start

# Run with default model (Gemini 2.5 Flash)
uv run zoo-eval run configs/tasks.yaml

# Run with different models
uv run zoo-eval run configs/tasks.yaml --model claude     # Claude Sonnet 4
uv run zoo-eval run configs/tasks.yaml --model gpt-4o     # OpenAI GPT-4o

# Use any OpenRouter model directly
uv run zoo-eval run configs/tasks.yaml --model anthropic/claude-sonnet-4

# Run specific tasks
uv run zoo-eval run configs/tasks.yaml --tasks 21,22,23

# Run with options
uv run zoo-eval run configs/tasks.yaml --limit 10 --timeout 180 --max-steps 30

# Resume an interrupted run
uv run zoo-eval run configs/tasks.yaml --resume
```

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
