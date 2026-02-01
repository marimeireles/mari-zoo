"""Benchmark runner for comprehensive evaluation across all tasks.

Provides one-line commands to run:
- All homogeneous (single-model) tasks
- All heterogeneous (multi-model) tasks

Outputs comprehensive metrics report to a timestamped directory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

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
    """Generate a cute random name for the benchmark run."""
    import random
    adjectives = ["swift", "bright", "calm", "bold", "keen", "warm", "cool", "quick"]
    nouns = ["fox", "owl", "wolf", "bear", "hawk", "lynx", "deer", "hare"]
    return f"{random.choice(adjectives)}_{random.choice(nouns)}"


def _create_output_dir(base_path: Path = Path("benchmark_results")) -> Path:
    """Create timestamped output directory with cute name."""
    timestamp = datetime.now().strftime("%d_%m_%y_%H_%M")
    name = _generate_run_name()
    dir_name = f"benchmark_{timestamp}_{name}"
    output_dir = base_path / dir_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


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
    avg_steps_per_task: float
    error_count: int

    # By autonomy level
    by_autonomy_level: dict[str, dict[str, Any]]
    autonomy_score: float  # (1×CR_L0 + 2×CR_L1 + 3×CR_L2) / 6

    # By environment
    by_environment: dict[str, dict[str, Any]]
    environment_resilience: float | None  # wild_score / domesticated_score

    # By complexity
    by_complexity: dict[str, dict[str, Any]]

    # Efficiency metrics
    avg_duration_per_success: float
    avg_steps_per_success: float

    # Subtask aggregates
    total_subtasks: int
    subtasks_passed: int
    subtask_pass_rate: float

    # Task-level details
    task_results: list[dict[str, Any]]

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
                "avg_steps_per_task": round(self.avg_steps_per_task, 2),
                "error_count": self.error_count,
            },
            "autonomy": {
                "by_level": self.by_autonomy_level,
                "autonomy_score": round(self.autonomy_score, 4),
            },
            "environment": {
                "by_type": self.by_environment,
                "resilience": round(self.environment_resilience, 4) if self.environment_resilience else None,
            },
            "complexity": {
                "by_type": self.by_complexity,
            },
            "efficiency": {
                "avg_duration_per_success": round(self.avg_duration_per_success, 2),
                "avg_steps_per_success": round(self.avg_steps_per_success, 2),
            },
            "subtasks": {
                "total": self.total_subtasks,
                "passed": self.subtasks_passed,
                "pass_rate": round(self.subtask_pass_rate, 4),
            },
            "task_results": self.task_results,
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

    # Autonomy Score = (1×CR_L0 + 2×CR_L1 + 3×CR_L2) / 6
    by_level = stats.get("by_level", {})
    weights = {"L0": 1, "L1": 2, "L2": 3}
    weighted_sum = 0.0
    for level, weight in weights.items():
        level_data = by_level.get(level, {})
        completion_rate = level_data.get("completion_rate", 0) / 100
        weighted_sum += weight * completion_rate
    autonomy_score = weighted_sum / 6

    # Environment Resilience = wild_score / domesticated_score
    by_env = stats.get("by_environment", {})
    dom_score = by_env.get("domesticated", {}).get("avg_score", 0)
    wild_score = by_env.get("wild", {}).get("avg_score", 0)
    environment_resilience = wild_score / dom_score if dom_score > 0 else None

    # Efficiency metrics per successful task
    successful_results = [r for r in results if r.get("score", 0) >= 1.0]
    if successful_results:
        avg_duration_per_success = sum(r.get("duration_seconds", 0) for r in successful_results) / len(successful_results)
        avg_steps_per_success = sum(r.get("steps", 0) for r in successful_results) / len(successful_results)
    else:
        avg_duration_per_success = 0
        avg_steps_per_success = 0

    # Format task results
    task_results = []
    for r in results:
        task_results.append({
            "task_id": r["task_id"],
            "task_name": r.get("task_name", ""),
            "autonomy_level": r.get("autonomy_level", "L1"),
            "complexity": r.get("complexity"),
            "environment": r.get("environment"),
            "score": round(r.get("score", 0), 4),
            "subtasks_passed": r.get("subtasks_passed", 0),
            "subtasks_total": r.get("subtasks_total", 0),
            "steps": r.get("steps", 0),
            "duration_seconds": round(r.get("duration_seconds", 0), 2),
            "error": r.get("error"),
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
        avg_steps_per_task=stats["avg_steps"],
        error_count=stats["errors"],
        by_autonomy_level=by_level,
        autonomy_score=autonomy_score,
        by_environment=by_env,
        environment_resilience=environment_resilience,
        by_complexity=stats.get("by_complexity", {}),
        avg_duration_per_success=avg_duration_per_success,
        avg_steps_per_success=avg_steps_per_success,
        task_results=task_results,
        total_subtasks=stats["total_subtasks"],
        subtasks_passed=stats["total_subtasks_passed"],
        subtask_pass_rate=stats["total_subtasks_passed"] / stats["total_subtasks"] if stats["total_subtasks"] else 0,
    )


async def run_benchmark(
    config: BenchmarkConfig,
    multi_model: bool = False,
    resume: bool = False,
) -> BenchmarkMetrics | None:
    """Run the benchmark suite.

    Args:
        config: Benchmark configuration
        multi_model: If True, run multi-model tasks; if False, run homogeneous tasks
        resume: Resume from previous run

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
    universes = discover_universes()
    if not universes:
        console.print("[red]No universes found in pet_to_wild/universes/[/red]")
        return None

    # Collect tasks based on benchmark type
    all_tasks: list[tuple[Path, Path, list[Task]]] = []
    benchmark_type = "multi_model" if multi_model else "homogeneous"

    for universe_path in universes:
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

    # Run each universe's tasks
    for universe_path, task_file, tasks in all_tasks:
        universe_obj = load_universe(universe_path)
        console.print(f"[cyan]{universe_obj.name}/{task_file.stem}[/cyan]")

        runner = TaskRunner(zoo, run_config, universe_path, universe_obj)
        await runner.setup()

        try:
            results = await runner.run_and_evaluate_batch(tasks, universe_obj.name)

            for result in results:
                db.save_result(run_id, result)
        finally:
            await runner.teardown()

    db.finish_run(run_id)

    # Compute metrics
    metrics = compute_metrics(db, run_id, config.model, config.harness, benchmark_type)

    # Export results
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(metrics.to_dict(), f, indent=2)

    console.print(f"[green]Results saved to {output_dir}[/green]")

    db.close()
    return metrics
