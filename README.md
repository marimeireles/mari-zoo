# zoo-eval

Web agent evaluation harness using [The Zoo](https://github.com/anthropics/the_zoo).

## Setup

```bash
# Install dependencies
uv sync

# Install playwright browsers
uv run playwright install chromium

# Set OpenAI API key
export OPENAI_API_KEY=your-key
```

## Running Evaluations

```bash
# Start The Zoo first
npx the_zoo start

# Run all tasks
uv run zoo-eval run configs/tasks.yaml

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
```
