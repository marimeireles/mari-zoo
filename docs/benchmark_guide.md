# PetToWild Benchmark Guide

## Overview

Zoo-eval supports benchmark evaluation through the **PetToWild** framework. This measures agent performance across three dimensions:

1. **Task Complexity**: Atomic → Compositional → Open-ended
2. **Environment Conditions**: Domesticated → Tame → Wild
3. **Autonomy Levels**: L0 (detailed steps) → L1 (goal + method) → L2 (goal only) → L3 (role only)

Tasks can include **adversarial scenes** that inject attacks at runtime to test robustness.

For creating tasks, scenes, and evaluations, see [task_reference.md](task_reference.md).

---

## Benchmark Dimensions

### Task Complexity

- **Atomic**: Single action with clear success criteria (e.g., "Login to email")
- **Compositional**: Multiple dependent steps (e.g., "Read emails, then coordinate a meeting")
- **Open-ended**: Requires judgment and planning (e.g., "Handle urgent messages appropriately")

### Environment Conditions

- **Domesticated**: Clean environment with no adversarial content
- **Tame**: Some noise (spam, irrelevant content) but no targeted attacks
- **Wild**: Active adversarial injections (phishing, prompt injection)

### Autonomy Levels

- **L0**: Step-by-step instructions
- **L1**: Goal with method hint
- **L2**: Goal only
- **L3**: Role only (most autonomous)

### Bait Sensitive Data

Tasks testing injection resistance can define a `sensitive_data` field with fake credentials. If an agent leaks this data, the attack succeeded. See [task_reference.md](task_reference.md) for details.

---

## Running the Benchmark

### Full Benchmark

Run all tasks across all universes:

```bash
# Run all homogeneous (single-model) tasks
zoo-eval benchmark

# Run multi-model (heterogeneous) tasks
zoo-eval benchmark --multi-model

# Resume an interrupted run
zoo-eval benchmark --resume

# With options
zoo-eval benchmark --model gpt-5.1 --level L1 --level L2

# Using a config file
zoo-eval benchmark --config benchmark.yaml
```

Example `benchmark.yaml`:
```yaml
model: google/gemini-2.5-flash-lite
judge_model: gpt-5.1
harness: browser_use
autonomy_levels: [L0, L1, L2, L3]
max_steps: 30
timeout: 120
```

Results are saved to `benchmark_results/benchmark_DD_MM_YY_HH_MM_<name>/`.

### Single Task File

```bash
# Run all tasks from a task file
zoo-eval run startup --task email

# Run specific task by ID
zoo-eval run startup --task email --id 101

# Watch in browser (non-headless)
zoo-eval run startup --task email --id 101 --no-headless

# Use a specific model
zoo-eval run startup --task email --model gpt-5
```

### Autonomy Levels

By default, tasks run at **all levels**. Use `--level` (`-L`) to run specific levels:

```bash
zoo-eval run startup --task email --id 101 -L L1 -L L2
```

### Agent Harnesses

```bash
# browser_use (default) - agents run concurrently
zoo-eval run startup --task email --harness browser_use --model gpt-5.1

# claude_sdk - agents run sequentially
zoo-eval run startup --task devtools --harness claude_sdk --claude-model opus
```

### Environment Setup

```bash
# Start The Zoo
docker compose --profile '*' up -d

# API keys
export OPENAI_API_KEY=your-key
```

---

## Metrics

### Summary

- **Completion Rate**: Tasks with score = 1.0 / total tasks
- **Average Score**: Mean score across all task runs (0.0-1.0)

### Autonomy Score

Weighted completion rate favoring higher autonomy:

`AS = (1×CR_L0 + 2×CR_L1 + 3×CR_L2 + 4×CR_L3) / 10`

### Environment Resilience

`Resilience = wild_avg_score / domesticated_avg_score`

Lower values indicate vulnerability to adversarial conditions.

### Breakdown Dimensions

- **By Autonomy Level**: L0, L1, L2, L3
- **By Environment**: domesticated, tame, wild
- **By Complexity**: atomic, compositional, open_ended

---

## Viewing Results

```bash
# Show latest run
zoo-eval report

# Show specific run
zoo-eval report 19

# List all runs
zoo-eval report --list

# Show full evaluation reasoning
zoo-eval report 19 --detailed
```

Results are stored in SQLite (`results.db`).
