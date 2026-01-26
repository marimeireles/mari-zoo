"""Benchmark runner for systematic evaluation studies."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
import statistics

from .models import AgentHarness, RunConfig, load_tasks, load_universe
from .results import ResultsDB
from .runner import TaskRunner
from .zoo import Zoo, ZooConfig


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark run."""

    name: str
    universe: str
    task_files: list[str]
    task_ids: list[int] | None = None  # None means all tasks in files
    models: list[str] = field(default_factory=lambda: ["google/gemini-2.5-flash-lite"])
    harnesses: list[str] = field(default_factory=lambda: ["browser_use"])
    autonomy_levels: list[str] = field(default_factory=lambda: ["L1"])
    trials_per_config: int = 1
    max_steps: int = 30
    timeout_seconds: float = 120.0
    headless: bool = True
    judge_model: str = "gpt-4o"

    def total_runs(self) -> int | None:
        """Calculate total number of runs.

        Returns None if task_ids is not specified (unknown until tasks are loaded).
        """
        if self.task_ids is None:
            return None
        return (
            len(self.task_ids)
            * len(self.models)
            * len(self.harnesses)
            * len(self.autonomy_levels)
            * self.trials_per_config
        )


@dataclass
class TrialResult:
    """Result of a single trial."""

    task_id: int
    model: str
    harness: str
    autonomy_level: str
    trial: int
    passed: bool
    steps: int
    duration_seconds: float
    error: str | None = None
    cost_usd: float | None = None
    eval_details: str | None = None


@dataclass
class BenchmarkResults:
    """Aggregated benchmark results."""

    config: BenchmarkConfig
    trials: list[TrialResult] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    total_duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "config": asdict(self.config),
            "trials": [asdict(t) for t in self.trials],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_duration_seconds": self.total_duration_seconds,
            "summary": self.summary(),
        }

    def summary(self) -> dict:
        """Generate summary statistics."""
        if not self.trials:
            return {}

        # Overall stats
        total = len(self.trials)
        passed = sum(1 for t in self.trials if t.passed)
        failed = total - passed

        # Group by dimensions
        by_model = self._group_stats("model")
        by_harness = self._group_stats("harness")
        by_level = self._group_stats("autonomy_level")
        by_task = self._group_stats("task_id")

        # Cross-tabulation: model x level
        model_level_matrix = {}
        for model in self.config.models:
            model_level_matrix[model] = {}
            for level in self.config.autonomy_levels:
                trials = [t for t in self.trials if t.model == model and t.autonomy_level == level]
                if trials:
                    model_level_matrix[model][level] = {
                        "pass_rate": sum(1 for t in trials if t.passed) / len(trials),
                        "avg_steps": statistics.mean(t.steps for t in trials),
                        "count": len(trials),
                    }

        return {
            "total_trials": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total if total > 0 else 0,
            "by_model": by_model,
            "by_harness": by_harness,
            "by_autonomy_level": by_level,
            "by_task": by_task,
            "model_level_matrix": model_level_matrix,
        }

    def _group_stats(self, key: str) -> dict:
        """Group trials by a key and compute stats."""
        groups = {}
        for trial in self.trials:
            value = getattr(trial, key)
            if value not in groups:
                groups[value] = []
            groups[value].append(trial)

        stats = {}
        for value, trials in groups.items():
            total = len(trials)
            passed = sum(1 for t in trials if t.passed)
            durations = [t.duration_seconds for t in trials]
            steps = [t.steps for t in trials]

            stats[str(value)] = {
                "total": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": passed / total if total > 0 else 0,
                "avg_duration": statistics.mean(durations) if durations else 0,
                "avg_steps": statistics.mean(steps) if steps else 0,
                "std_steps": statistics.stdev(steps) if len(steps) > 1 else 0,
            }

        return stats

    def pass_rate_table(self) -> str:
        """Generate ASCII table of pass rates by model and level."""
        summary = self.summary()
        matrix = summary.get("model_level_matrix", {})

        if not matrix:
            return "No data"

        # Header
        levels = self.config.autonomy_levels
        header = "Model".ljust(25) + "".join(lvl.center(10) for lvl in levels)
        lines = [header, "-" * len(header)]

        # Rows
        for model in self.config.models:
            row = model[:24].ljust(25)
            for level in levels:
                data = matrix.get(model, {}).get(level, {})
                rate = data.get("pass_rate", 0)
                row += f"{rate*100:.1f}%".center(10)
            lines.append(row)

        return "\n".join(lines)


class BenchmarkRunner:
    """Runs systematic benchmarks across configurations."""

    def __init__(self, config: BenchmarkConfig, zoo: Zoo, db_path: Path = Path("benchmark.db")):
        self.config = config
        self.zoo = zoo
        self.db_path = db_path
        self.results = BenchmarkResults(config=config)

    async def run(self, verbose: bool = True) -> BenchmarkResults:
        """Run the full benchmark."""
        self.results.started_at = datetime.now().isoformat()
        start_time = time.time()

        # Load universe
        universe_path = Path(self.config.universe)
        if not universe_path.exists():
            universe_path = Path("pet_to_wild/universes") / self.config.universe
        universe = load_universe(universe_path)

        # Load tasks from all task files
        all_tasks = []
        for task_file in self.config.task_files:
            task_path = universe_path / "tasks" / f"{task_file}.yaml"
            if not task_path.exists():
                task_path = universe_path / "tasks" / f"{task_file}.yml"
            if task_path.exists():
                tasks = load_tasks(task_path)
                all_tasks.extend(tasks)
            else:
                print(f"Warning: Task file not found: {task_file} (tried .yaml and .yml)")

        # Filter by task IDs if specified
        if self.config.task_ids:
            all_tasks = [t for t in all_tasks if t.task_id in self.config.task_ids]

        if not all_tasks:
            print("No tasks to run!")
            return self.results

        total_configs = (
            len(all_tasks)
            * len(self.config.models)
            * len(self.config.harnesses)
            * len(self.config.autonomy_levels)
            * self.config.trials_per_config
        )

        if verbose:
            print(f"Benchmark: {self.config.name}")
            print(f"  Tasks: {len(all_tasks)}")
            print(f"  Models: {self.config.models}")
            print(f"  Harnesses: {self.config.harnesses}")
            print(f"  Levels: {self.config.autonomy_levels}")
            print(f"  Trials per config: {self.config.trials_per_config}")
            print(f"  Total runs: {total_configs}")
            print()

        run_count = 0
        for model in self.config.models:
            for harness_str in self.config.harnesses:
                harness = AgentHarness(harness_str)

                for level in self.config.autonomy_levels:
                    for trial in range(self.config.trials_per_config):
                        for task in all_tasks:
                            run_count += 1
                            if verbose:
                                print(
                                    f"[{run_count}/{total_configs}] "
                                    f"Task {task.task_id}, {model}, {harness_str}, {level}, trial {trial + 1}"
                                )

                            trial_result = await self._run_single_trial(
                                task=task,
                                model=model,
                                harness=harness,
                                level=level,
                                trial=trial + 1,
                                universe_path=universe_path,
                                universe=universe,
                            )
                            self.results.trials.append(trial_result)

                            status = "PASS" if trial_result.passed else "FAIL"
                            if verbose:
                                print(f"    → {status} ({trial_result.duration_seconds:.1f}s, {trial_result.steps} steps)")

        self.results.finished_at = datetime.now().isoformat()
        self.results.total_duration_seconds = time.time() - start_time

        return self.results

    async def _run_single_trial(
        self,
        task,
        model: str,
        harness: AgentHarness,
        level: str,
        trial: int,
        universe_path: Path,
        universe,
    ) -> TrialResult:
        """Run a single trial and return the result."""
        start_time = time.time()

        # Determine claude_model if using Claude SDK
        claude_model = "sonnet"
        if harness == AgentHarness.CLAUDE_SDK:
            if "opus" in model.lower():
                claude_model = "opus"
            elif "haiku" in model.lower():
                claude_model = "haiku"

        run_config = RunConfig(
            headless=self.config.headless,
            max_steps=self.config.max_steps,
            timeout_seconds=self.config.timeout_seconds,
            model=model,
            judge_model=self.config.judge_model,
            autonomy_levels=[level],
            harness=harness,
            claude_model=claude_model,
            skip_zoo_reset=True,  # Don't reset between trials
        )

        runner = TaskRunner(self.zoo, run_config, universe_path, universe)

        try:
            await runner.setup()
            results = await runner.run_and_evaluate_batch([task], universe.name)
            await runner.teardown()

            if results:
                result = results[0]
                return TrialResult(
                    task_id=task.task_id,
                    model=model,
                    harness=harness.value,
                    autonomy_level=level,
                    trial=trial,
                    passed=result.passed,
                    steps=result.task_result.steps,
                    duration_seconds=result.task_result.duration_seconds,
                    eval_details=str(result.eval_results) if result.eval_results else None,
                )
            else:
                return TrialResult(
                    task_id=task.task_id,
                    model=model,
                    harness=harness.value,
                    autonomy_level=level,
                    trial=trial,
                    passed=False,
                    steps=0,
                    duration_seconds=0,
                    error="No results returned",
                )

        except Exception as e:
            import traceback
            return TrialResult(
                task_id=task.task_id,
                model=model,
                harness=harness.value,
                autonomy_level=level,
                trial=trial,
                passed=False,
                steps=0,
                duration_seconds=time.time() - start_time,
                error=f"{str(e)}\n{traceback.format_exc()}",
            )

    def save_results(self, output_path: Path) -> None:
        """Save results to JSON file."""
        with open(output_path, "w") as f:
            json.dump(self.results.to_dict(), f, indent=2)


def generate_report(results: BenchmarkResults, format: str = "text") -> str:
    """Generate a report from benchmark results."""
    if format == "text":
        return _generate_text_report(results)
    elif format == "markdown":
        return _generate_markdown_report(results)
    else:
        raise ValueError(f"Unknown format: {format}")


def _generate_text_report(results: BenchmarkResults) -> str:
    """Generate plain text report."""
    lines = []
    summary = results.summary()

    lines.append(f"Benchmark Report: {results.config.name}")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Started: {results.started_at}")
    lines.append(f"Finished: {results.finished_at}")
    lines.append(f"Duration: {results.total_duration_seconds:.1f}s")
    lines.append("")
    lines.append("Configuration:")
    lines.append(f"  Universe: {results.config.universe}")
    lines.append(f"  Tasks: {results.config.task_files}")
    lines.append(f"  Models: {results.config.models}")
    lines.append(f"  Harnesses: {results.config.harnesses}")
    lines.append(f"  Autonomy Levels: {results.config.autonomy_levels}")
    lines.append(f"  Trials per config: {results.config.trials_per_config}")
    lines.append("")
    lines.append("Overall Results:")
    lines.append(f"  Total trials: {summary.get('total_trials', 0)}")
    lines.append(f"  Passed: {summary.get('passed', 0)}")
    lines.append(f"  Failed: {summary.get('failed', 0)}")
    lines.append(f"  Pass rate: {summary.get('pass_rate', 0)*100:.1f}%")
    lines.append("")
    lines.append("Pass Rate by Model and Autonomy Level:")
    lines.append(results.pass_rate_table())
    lines.append("")

    # Per-model breakdown
    by_model = summary.get("by_model", {})
    if by_model:
        lines.append("By Model:")
        for model, stats in by_model.items():
            lines.append(
                f"  {model}: {stats['pass_rate']*100:.1f}% "
                f"({stats['passed']}/{stats['total']}) "
                f"avg {stats['avg_steps']:.1f} steps"
            )
        lines.append("")

    # Per-task breakdown
    by_task = summary.get("by_task", {})
    if by_task:
        lines.append("By Task:")
        for task_id, stats in sorted(by_task.items(), key=lambda x: int(x[0])):
            lines.append(
                f"  Task {task_id}: {stats['pass_rate']*100:.1f}% "
                f"({stats['passed']}/{stats['total']})"
            )

    return "\n".join(lines)


def _generate_markdown_report(results: BenchmarkResults) -> str:
    """Generate markdown report."""
    lines = []
    summary = results.summary()

    lines.append(f"# Benchmark Report: {results.config.name}")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append(f"- **Started:** {results.started_at}")
    lines.append(f"- **Finished:** {results.finished_at}")
    lines.append(f"- **Duration:** {results.total_duration_seconds:.1f}s")
    lines.append(f"- **Total Trials:** {summary.get('total_trials', 0)}")
    lines.append(f"- **Pass Rate:** {summary.get('pass_rate', 0)*100:.1f}%")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Universe: `{results.config.universe}`")
    lines.append(f"- Tasks: `{results.config.task_files}`")
    lines.append(f"- Models: `{results.config.models}`")
    lines.append(f"- Harnesses: `{results.config.harnesses}`")
    lines.append(f"- Autonomy Levels: `{results.config.autonomy_levels}`")
    lines.append(f"- Trials per config: {results.config.trials_per_config}")
    lines.append("")
    lines.append("## Results by Model and Autonomy Level")
    lines.append("")

    # Markdown table
    matrix = summary.get("model_level_matrix", {})
    if matrix:
        levels = results.config.autonomy_levels
        lines.append("| Model | " + " | ".join(levels) + " |")
        lines.append("|" + "---|" * (len(levels) + 1))

        for model in results.config.models:
            row = f"| {model} |"
            for level in levels:
                data = matrix.get(model, {}).get(level, {})
                rate = data.get("pass_rate", 0)
                row += f" {rate*100:.1f}% |"
            lines.append(row)

    lines.append("")
    lines.append("## Results by Task")
    lines.append("")

    by_task = summary.get("by_task", {})
    if by_task:
        lines.append("| Task | Pass Rate | Passed | Total | Avg Steps |")
        lines.append("|------|-----------|--------|-------|-----------|")
        for task_id, stats in sorted(by_task.items(), key=lambda x: int(x[0])):
            lines.append(
                f"| {task_id} | {stats['pass_rate']*100:.1f}% | "
                f"{stats['passed']} | {stats['total']} | {stats['avg_steps']:.1f} |"
            )

    return "\n".join(lines)
