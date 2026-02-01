"""Benchmark runner for comprehensive evaluation across all tasks.

Provides one-line commands to run:
- All homogeneous (single-model) tasks
- All heterogeneous (multi-model) tasks

Outputs comprehensive metrics report to a timestamped directory.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn

from .models import (
    AUTONOMY_LEVELS,
    COMPLEXITIES,
    ENVIRONMENTS,
    AgentHarness,
    RunConfig,
    Task,
    load_tasks,
    load_universe,
)
from .results import ResultsDB
from .runner import TaskRunner
from .zoo import Zoo, ZooConfig

console = Console()

# Task files that contain heterogeneous (multi-model) tasks
MULTI_MODEL_TASK_FILES = {"multi_model"}


def _generate_run_name() -> str:
    """Generate a cute random name for the run."""
    import random
    adjectives = ["swift", "bright", "calm", "bold", "keen", "warm", "cool", "quick"]
    nouns = ["fox", "owl", "wolf", "bear", "hawk", "lynx", "deer", "hare"]
    return f"{random.choice(adjectives)}_{random.choice(nouns)}"


def _create_output_dir(base_path: Path = Path("benchmark_results")) -> Path:
    """Create timestamped output directory for benchmark results."""
    timestamp = datetime.now().strftime("%d_%m_%y_%H_%M")
    name = _generate_run_name()
    dir_name = f"benchmark_{timestamp}_{name}"
    output_dir = base_path / dir_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def create_log_dir(prefix: str = "run", universe: str = "", task_file: str = "") -> Path:
    """Create a log directory for any run (benchmark or individual)."""
    timestamp = datetime.now().strftime("%d-%m-%y_%H-%M-%S")
    name = _generate_run_name()
    parts = [prefix, timestamp]
    if universe:
        parts.append(universe)
    if task_file:
        parts.append(task_file)
    parts.append(name)
    dir_name = "_".join(parts)
    log_dir = Path("logs") / dir_name
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark runs."""

    model: str = "google/gemini-2.5-flash-lite"
    judge_model: str = "gpt-5.1"
    harness: str = "browser_use"
    claude_model: str = "sonnet"
    headless: bool = True
    max_steps: int = 30
    timeout: int = 120
    autonomy_levels: list[str] = field(default_factory=lambda: list(AUTONOMY_LEVELS))
    proxy_port: int = 3128
    use_proxy_events: bool = False
    redis_url: str = "redis://localhost:6379"
    db_path: str = "results.db"
    output_dir: str | None = None  # Auto-generated if not specified

    @classmethod
    def from_yaml(cls, path: Path) -> "BenchmarkConfig":
        """Load configuration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(
            model=data.get("model", cls.model),
            judge_model=data.get("judge_model", cls.judge_model),
            harness=data.get("harness", cls.harness),
            claude_model=data.get("claude_model", cls.claude_model),
            headless=data.get("headless", cls.headless),
            max_steps=data.get("max_steps", cls.max_steps),
            timeout=data.get("timeout", cls.timeout),
            autonomy_levels=data.get("autonomy_levels", list(AUTONOMY_LEVELS)),
            proxy_port=data.get("proxy_port", cls.proxy_port),
            use_proxy_events=data.get("use_proxy_events", cls.use_proxy_events),
            redis_url=data.get("redis_url", cls.redis_url),
            db_path=data.get("db_path", cls.db_path),
            output_dir=data.get("output_dir"),
        )

    def to_yaml(self, path: Path):
        """Save configuration to YAML file."""
        data = {
            "model": self.model,
            "judge_model": self.judge_model,
            "harness": self.harness,
            "claude_model": self.claude_model,
            "headless": self.headless,
            "max_steps": self.max_steps,
            "timeout": self.timeout,
            "autonomy_levels": self.autonomy_levels,
            "proxy_port": self.proxy_port,
            "use_proxy_events": self.use_proxy_events,
            "redis_url": self.redis_url,
            "db_path": self.db_path,
        }
        if self.output_dir:
            data["output_dir"] = self.output_dir
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

    def get_harness_enum(self) -> AgentHarness:
        """Convert harness string to enum."""
        return AgentHarness(self.harness)


def discover_universes(base_path: Path = Path("pet_to_wild/universes")) -> list[Path]:
    """Discover all universe directories."""
    if not base_path.exists():
        return []
    return [p for p in base_path.iterdir() if p.is_dir() and (p / "config.yaml").exists()]


def discover_task_files(universe_path: Path, exclude_multi_model: bool = False) -> list[Path]:
    """Discover task files in a universe."""
    tasks_dir = universe_path / "tasks"
    if not tasks_dir.exists():
        return []

    task_files = list(tasks_dir.glob("*.yaml")) + list(tasks_dir.glob("*.yml"))

    if exclude_multi_model:
        task_files = [f for f in task_files if f.stem not in MULTI_MODEL_TASK_FILES]

    return task_files


def discover_multi_model_task_files(universe_path: Path) -> list[Path]:
    """Discover only multi-model task files in a universe."""
    tasks_dir = universe_path / "tasks"
    if not tasks_dir.exists():
        return []

    return [
        f
        for f in (list(tasks_dir.glob("*.yaml")) + list(tasks_dir.glob("*.yml")))
        if f.stem in MULTI_MODEL_TASK_FILES
    ]


@dataclass
class BenchmarkMetrics:
    """Comprehensive benchmark metrics."""

    run_id: int
    started_at: str
    finished_at: str | None
    model: str
    harness: str
    benchmark_type: str

    # Base stats
    total_tasks: int
    total_completed: int
    overall_score: float
    overall_completion_rate: float
    total_duration_seconds: float
    avg_duration_per_task: float
    total_steps: int
    avg_steps_per_task: float
    error_count: int

    # By autonomy level
    by_autonomy_level: dict[str, dict[str, Any]]
    autonomy_score: float  # (1×CR_L0 + 2×CR_L1 + 3×CR_L2) / 6

    # By environment
    by_environment: dict[str, dict[str, Any]]

    # By complexity (with efficiency)
    by_complexity: dict[str, dict[str, Any]]

    # Hierarchical breakdown: universe → task_file → task
    by_universe: dict[str, dict[str, Any]]

    # Overall efficiency
    avg_duration_per_success: float
    avg_steps_per_success: float

    # Raw results for CSV export (not included in JSON)
    _raw_results: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON export."""
        return {
            "metadata": {
                "run_id": self.run_id,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "model": self.model,
                "harness": self.harness,
                "benchmark_type": self.benchmark_type,
            },
            "summary": {
                "total_tasks": self.total_tasks,
                "total_completed": self.total_completed,
                "overall_score": round(self.overall_score, 4),
                "overall_completion_rate": round(self.overall_completion_rate, 4),
                "total_duration_seconds": round(self.total_duration_seconds, 2),
                "avg_duration_per_task": round(self.avg_duration_per_task, 2),
                "total_steps": self.total_steps,
                "avg_steps_per_task": round(self.avg_steps_per_task, 2),
                "error_count": self.error_count,
            },
            "autonomy": {
                "by_level": self.by_autonomy_level,
                "autonomy_score": round(self.autonomy_score, 4),
            },
            "environment": {
                "by_type": self.by_environment,
            },
            "complexity": {
                "by_type": self.by_complexity,
            },
            "efficiency": {
                "avg_duration_per_success": round(self.avg_duration_per_success, 2),
                "avg_steps_per_success": round(self.avg_steps_per_success, 2),
            },
            "by_universe": self.by_universe,
        }

    def to_csv_rows(self) -> list[dict[str, Any]]:
        """Convert raw results to CSV-friendly rows."""
        return self._raw_results


def _compute_group_stats(results: list[dict]) -> dict[str, Any]:
    """Compute stats for a group of results."""
    if not results:
        return {"total": 0, "completed": 0, "completion_rate": 0, "avg_score": 0,
                "avg_duration": 0, "avg_steps": 0}

    total = len(results)
    completed = sum(1 for r in results if r.get("score", 0) >= 1.0)
    avg_score = sum(r.get("score", 0) for r in results) / total
    avg_duration = sum(r.get("duration_seconds", 0) for r in results) / total
    avg_steps = sum(r.get("steps", 0) for r in results) / total

    return {
        "total": total,
        "completed": completed,
        "completion_rate": round(completed / total * 100, 2),
        "avg_score": round(avg_score, 4),
        "avg_duration": round(avg_duration, 2),
        "avg_steps": round(avg_steps, 2),
    }


def _compute_efficiency_stats(results: list[dict]) -> dict[str, float]:
    """Compute efficiency stats for successful results only."""
    successful = [r for r in results if r.get("score", 0) >= 1.0]
    if not successful:
        return {"avg_duration_per_success": 0, "avg_steps_per_success": 0}

    return {
        "avg_duration_per_success": round(
            sum(r.get("duration_seconds", 0) for r in successful) / len(successful), 2
        ),
        "avg_steps_per_success": round(
            sum(r.get("steps", 0) for r in successful) / len(successful), 2
        ),
    }


def compute_metrics(
    db: ResultsDB, run_id: int, model: str, harness: str, benchmark_type: str
) -> BenchmarkMetrics:
    """Compute comprehensive metrics from a benchmark run."""
    stats = db.get_run_stats(run_id)
    results = db.get_run_results(run_id)

    run_row = db.conn.execute(
        "SELECT started_at, finished_at FROM runs WHERE id = ?", (run_id,)
    ).fetchone()

    # By autonomy level with efficiency
    by_level = {}
    for level in AUTONOMY_LEVELS:
        level_results = [r for r in results if r.get("autonomy_level") == level]
        if level_results:
            by_level[level] = {
                **_compute_group_stats(level_results),
                **_compute_efficiency_stats(level_results),
            }
        else:
            by_level[level] = {"total": 0, "completed": 0, "completion_rate": 0, "avg_score": 0,
                              "avg_duration": 0, "avg_steps": 0,
                              "avg_duration_per_success": 0, "avg_steps_per_success": 0}

    # Autonomy Score = (1×CR_L0 + 2×CR_L1 + 3×CR_L2) / 6
    weights = {"L0": 1, "L1": 2, "L2": 3}
    weighted_sum = 0.0
    for level, weight in weights.items():
        level_data = by_level.get(level, {})
        completion_rate = level_data.get("completion_rate", 0) / 100
        weighted_sum += weight * completion_rate
    autonomy_score = weighted_sum / 6

    # By environment with efficiency
    by_env = {}
    for env in ENVIRONMENTS:
        env_results = [r for r in results if r.get("environment") == env]
        if env_results:
            by_env[env] = {
                **_compute_group_stats(env_results),
                **_compute_efficiency_stats(env_results),
            }

    # By complexity with efficiency
    by_complexity = {}
    for complexity in COMPLEXITIES:
        complexity_results = [r for r in results if r.get("complexity") == complexity]
        if complexity_results:
            by_complexity[complexity] = {
                **_compute_group_stats(complexity_results),
                **_compute_efficiency_stats(complexity_results),
            }

    # Hierarchical breakdown: universe → task_file → task
    by_universe: dict[str, Any] = {}

    for r in results:
        universe = r.get("universe") or "unknown"
        task_file = r.get("task_file") or "unknown"
        task_id = r["task_id"]

        if universe not in by_universe:
            by_universe[universe] = {"task_files": {}, "_results": []}
        by_universe[universe]["_results"].append(r)

        if task_file not in by_universe[universe]["task_files"]:
            by_universe[universe]["task_files"][task_file] = {"tasks": {}, "_results": []}
        by_universe[universe]["task_files"][task_file]["_results"].append(r)

        if task_id not in by_universe[universe]["task_files"][task_file]["tasks"]:
            by_universe[universe]["task_files"][task_file]["tasks"][task_id] = []
        by_universe[universe]["task_files"][task_file]["tasks"][task_id].append(r)

    # Compute stats at each level
    for universe, udata in by_universe.items():
        universe_results = udata.pop("_results")
        udata.update(_compute_group_stats(universe_results))
        udata.update(_compute_efficiency_stats(universe_results))

        for task_file, tfdata in udata["task_files"].items():
            tf_results = tfdata.pop("_results")
            tfdata.update(_compute_group_stats(tf_results))
            tfdata.update(_compute_efficiency_stats(tf_results))

            for task_id, task_results in tfdata["tasks"].items():
                tfdata["tasks"][task_id] = {
                    **_compute_group_stats(task_results),
                    **_compute_efficiency_stats(task_results),
                }

    # Overall efficiency
    successful_results = [r for r in results if r.get("score", 0) >= 1.0]
    if successful_results:
        avg_duration_per_success = sum(r.get("duration_seconds", 0) for r in successful_results) / len(successful_results)
        avg_steps_per_success = sum(r.get("steps", 0) for r in successful_results) / len(successful_results)
    else:
        avg_duration_per_success = 0
        avg_steps_per_success = 0

    # Format raw results for CSV export
    csv_results = []
    for r in results:
        csv_results.append({
            "universe": r.get("universe", ""),
            "task_file": r.get("task_file", ""),
            "task_id": r["task_id"],
            "task_name": r.get("task_name", ""),
            "autonomy_level": r.get("autonomy_level", "L1"),
            "complexity": r.get("complexity", ""),
            "environment": r.get("environment", ""),
            "score": round(r.get("score", 0), 4),
            "completed": 1 if r.get("score", 0) >= 1.0 else 0,
            "steps": r.get("steps", 0),
            "duration_seconds": round(r.get("duration_seconds", 0), 2),
            "subtasks_passed": r.get("subtasks_passed", 0),
            "subtasks_total": r.get("subtasks_total", 0),
            "error": r.get("error", ""),
        })

    return BenchmarkMetrics(
        run_id=run_id,
        started_at=run_row["started_at"] if run_row else "",
        finished_at=run_row["finished_at"] if run_row else None,
        model=model,
        harness=harness,
        benchmark_type=benchmark_type,
        total_tasks=stats["total"],
        total_completed=stats["completed"],
        overall_score=stats["avg_score"],
        overall_completion_rate=stats["completion_rate"] / 100,
        total_duration_seconds=stats["total_duration"],
        avg_duration_per_task=stats["avg_duration"],
        total_steps=stats["total_steps"],
        avg_steps_per_task=stats["avg_steps"],
        error_count=stats["errors"],
        by_autonomy_level=by_level,
        autonomy_score=autonomy_score,
        by_environment=by_env,
        by_complexity=by_complexity,
        by_universe=by_universe,
        avg_duration_per_success=avg_duration_per_success,
        avg_steps_per_success=avg_steps_per_success,
        _raw_results=csv_results,
    )


async def run_benchmark(
    config: BenchmarkConfig,
    multi_model: bool = False,
    resume: bool = False,
    universes: list[str] | None = None,
) -> BenchmarkMetrics | None:
    """Run the benchmark suite.

    Args:
        config: Benchmark configuration
        multi_model: If True, run multi-model tasks; if False, run homogeneous tasks
        resume: Resume from previous run
        universes: List of universe names to run (default: all)

    Returns:
        BenchmarkMetrics or None if no tasks to run
    """
    # Check Zoo is running
    zoo_config = ZooConfig(proxy_url=f"http://localhost:{config.proxy_port}")
    zoo = Zoo(zoo_config)
    if not zoo.is_running():
        console.print("[red]Zoo is not running.[/red]")
        return None

    # Discover universes and tasks
    all_universe_paths = discover_universes()
    if not all_universe_paths:
        console.print("[red]No universes found in pet_to_wild/universes/[/red]")
        return None

    # Filter universes if specified
    if universes:
        universe_set = set(universes)
        universe_paths = [p for p in all_universe_paths if p.name in universe_set]
        if not universe_paths:
            available = [p.name for p in all_universe_paths]
            console.print(f"[red]No matching universes found. Available: {', '.join(available)}[/red]")
            return None
    else:
        universe_paths = all_universe_paths

    # Collect tasks based on benchmark type
    all_tasks: list[tuple[Path, Path, list[Task]]] = []
    benchmark_type = "multi_model" if multi_model else "homogeneous"

    for universe_path in universe_paths:
        universe_obj = load_universe(universe_path)

        if multi_model:
            task_files = discover_multi_model_task_files(universe_path)
        else:
            task_files = discover_task_files(universe_path, exclude_multi_model=True)

        for task_file in task_files:
            try:
                tasks = load_tasks(task_file)
                compatible_tasks = [
                    t for t in tasks
                    if not t.compatible_universes or universe_obj.name in t.compatible_universes
                ]
                if compatible_tasks:
                    all_tasks.append((universe_path, task_file, compatible_tasks))
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to load {task_file}: {e}[/yellow]")

    if not all_tasks:
        console.print("[yellow]No tasks found to run[/yellow]")
        return None

    total_task_count = sum(len(tasks) for _, _, tasks in all_tasks)
    total_runs = total_task_count * len(config.autonomy_levels)
    console.print(f"[bold]Benchmark ({benchmark_type}): {total_task_count} tasks × {len(config.autonomy_levels)} levels = {total_runs} evaluations[/bold]")

    # Setup output directory
    if config.output_dir:
        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = _create_output_dir()

    console.print(f"Output: {output_dir}")

    # Setup database
    db = ResultsDB(Path(config.db_path))

    tasks_info = f"benchmark:{benchmark_type}"
    completed_pairs: set[tuple[int, str]] = set()

    if resume:
        run_id = db.get_latest_run()
        if run_id:
            completed_pairs = db.get_completed_task_level_pairs(run_id)
            console.print(f"Resuming run #{run_id}: {len(completed_pairs)} pairs done")
        else:
            run_id = db.create_run(
                config_path="benchmark",
                universe="all",
                model=config.model,
                tasks=tasks_info,
            )
    else:
        run_id = db.create_run(
            config_path="benchmark",
            universe="all",
            model=config.model,
            tasks=tasks_info,
        )

    # Save config to output directory
    config.to_yaml(output_dir / "config.yaml")

    # Create log directory for incremental logging
    log_dir = create_log_dir("benchmark", benchmark_type)
    console.print(f"Logs: {log_dir}")

    # Initialize log file with run info
    log_file = log_dir / "run.log"
    with open(log_file, "w") as f:
        f.write(f"Benchmark Run #{run_id}\n")
        f.write(f"Type: {benchmark_type}\n")
        f.write(f"Model: {config.model}\n")
        f.write(f"Harness: {config.harness}\n")
        f.write(f"Total tasks: {total_runs}\n")
        f.write(f"Output: {output_dir}\n")
        f.write("-" * 50 + "\n")

    # Run config
    run_config = RunConfig(
        headless=config.headless,
        max_steps=config.max_steps,
        timeout_seconds=config.timeout,
        model=config.model,
        judge_model=config.judge_model,
        shared_browser=False,
        autonomy_levels=config.autonomy_levels,
        completed_pairs=completed_pairs,
        harness=config.get_harness_enum(),
        claude_model=config.claude_model,
        use_proxy_events=config.use_proxy_events,
        redis_url=config.redis_url,
    )

    # Run each universe's tasks with progress bar
    completed_count = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_progress = progress.add_task(
            f"[cyan]Running {benchmark_type} benchmark...", total=total_runs
        )

        for universe_path, task_file, tasks in all_tasks:
            universe_obj = load_universe(universe_path)
            progress.update(task_progress, description=f"[cyan]{universe_obj.name}/{task_file.stem}")

            runner = TaskRunner(zoo, run_config, universe_path, universe_obj)
            await runner.setup()

            try:
                results = await runner.run_and_evaluate_batch(tasks, universe_obj.name, task_file.stem)

                for result in results:
                    db.save_result(run_id, result)
                    completed_count += 1
                    progress.update(task_progress, completed=completed_count)
                    # Log result incrementally
                    with open(log_file, "a") as f:
                        status = "✓" if result.score >= 1.0 else "✗"
                        f.write(f"{status} Task {result.task.task_id} ({result.task_result.autonomy_level}): {result.score:.2f} ({result.task_result.duration_seconds:.1f}s)\n")
            finally:
                await runner.teardown()

    db.finish_run(run_id)

    # Compute metrics
    metrics = compute_metrics(db, run_id, config.model, config.harness, benchmark_type)

    # Export JSON metrics
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(metrics.to_dict(), f, indent=2)

    # Export CSV results
    csv_rows = metrics.to_csv_rows()
    if csv_rows:
        csv_path = output_dir / "results.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=csv_rows[0].keys())
            writer.writeheader()
            writer.writerows(csv_rows)
        console.print(f"[green]Results saved to {output_dir} (metrics.json + results.csv)[/green]")
    else:
        console.print(f"[green]Results saved to {output_dir}[/green]")

    db.close()
    return metrics
