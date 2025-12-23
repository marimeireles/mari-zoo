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

# Run with default model (gpt-4o)
uv run zoo-eval run configs/tasks.yaml

# Run with different models
uv run zoo-eval run configs/tasks.yaml --model flash      # Gemini 2.0 Flash
uv run zoo-eval run configs/tasks.yaml --model claude     # Claude Sonnet 4
uv run zoo-eval run configs/tasks.yaml --model gpt-4o     # OpenAI GPT-4o

# Use any OpenRouter model directly
uv run zoo-eval run configs/tasks.yaml --model google/gemini-2.0-flash-001
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
```
