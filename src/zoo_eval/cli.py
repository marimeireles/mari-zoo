"""Command-line interface for zoo-eval."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .benchmark import BenchmarkConfig, create_log_dir, run_benchmark, _extract_harness_details
from .models import AUTONOMY_LEVELS, AgentHarness, RunConfig, load_tasks, load_universe
from .results import ResultsDB, print_report
from .runner import TaskRunner
from .zoo import Zoo, ZooConfig

app = typer.Typer(
    help="Web agent evaluation harness using The Zoo",
    add_completion=False,
)
console = Console()


@app.command()
def status(
    proxy_port: int = typer.Option(3128, "--proxy-port", "-p", help="Zoo proxy port"),
):
    """Check if Zoo is running and accessible."""
    zoo_config = ZooConfig(proxy_url=f"http://localhost:{proxy_port}")
    zoo = Zoo(zoo_config)
    if zoo.is_running():
        console.print(f"[green]Zoo is running on port {proxy_port}[/green]")
    else:
        console.print(f"[red]Zoo is not accessible on port {proxy_port}[/red]")
        raise typer.Exit(1)


@app.command()
def list_tasks(
    config: Path = typer.Argument(..., help="Path to tasks JSON file"),
    limit: int = typer.Option(10, help="Number of tasks to show"),
):
    """List tasks from a config file."""
    tasks = load_tasks(config, limit=limit)

    table = Table(title=f"Tasks from {config.name}")
    table.add_column("ID", style="cyan")
    table.add_column("Sites", style="green")
    table.add_column("Intent", style="white", max_width=60)
    table.add_column("Eval Types", style="yellow")

    for task in tasks:
        table.add_row(
            str(task.task_id),
            ", ".join(task.sites),
            task.intent[:60] + "..." if len(task.intent) > 60 else task.intent,
            ", ".join(e.value for e in task.evaluation.eval_types),
        )

    console.print(table)


@app.command()
def run(
    universe: Path = typer.Argument(..., help="Path to universe directory (contains config.yaml, tasks/, scenes/)"),
    task_file: str = typer.Option(..., "--task", "-t", help="Task file name (without .yaml)"),
    task_id: list[int] = typer.Option(None, "--id", "-i", help="Task ID(s) to run (optional, runs all if not specified)"),
    limit: int = typer.Option(None, "--limit", "-n", help="Max tasks to run"),
    headless: bool = typer.Option(True, help="Run browser headlessly"),
    max_steps: int = typer.Option(30, help="Max steps per task"),
    timeout: int = typer.Option(120, help="Timeout in seconds per task"),
    model: str = typer.Option("google/gemini-2.5-flash-lite", "--model", "-m", help="Agent model (auto-detects: '/' → OpenRouter, else OpenAI). Aliases: flash, sonnet"),
    judge_model: str = typer.Option(None, "--judge-model", "-j", help="LLM judge model (default: gpt-5.1, auto-detects provider like --model)"),
    shared_browser: bool = typer.Option(False, "--shared-browser", help="All agents share same browser and memory"),
    level: list[str] = typer.Option(None, "--level", "-L", help="Autonomy level(s) to run: L0, L1, L2 (can specify multiple, default: all)"),
    harness: str = typer.Option("browser_use", "--harness", "-H", help="Agent harness to use"),
    claude_model: str = typer.Option("sonnet", "--claude-model", help="Claude model for claude_sdk harness: opus, sonnet, haiku"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Resume from last run"),
    db_path: Path = typer.Option("results.db", "--db", help="Results database path"),
    proxy_port: int = typer.Option(3128, "--proxy-port", "-p", help="Zoo proxy port"),
    use_proxy_events: bool = typer.Option(False, "--use-proxy-events", help="Force proxy events (auto-detected from scene request triggers)"),
    redis_url: str = typer.Option("redis://localhost:6379", "--redis-url", help="Redis URL for proxy events"),
):
    """Run evaluation tasks from a universe directory."""
    # Validate harness
    try:
        harness_enum = AgentHarness(harness)
    except ValueError:
        console.print(f"[red]Invalid harness: {harness}. Valid: browser_use, claude_sdk[/red]")
        raise typer.Exit(1)

    # Validate environment for Claude SDK
    if harness_enum == AgentHarness.CLAUDE_SDK:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            console.print("[red]ANTHROPIC_API_KEY environment variable required for claude_sdk harness[/red]")
            raise typer.Exit(1)
    # Resolve universe path
    universe_path = Path(universe)
    if not universe_path.exists():
        # Try looking in pet_to_wild/universes/
        universe_path = Path("pet_to_wild/universes") / universe
    if not universe_path.exists():
        console.print(f"[red]Universe not found: {universe}[/red]")
        raise typer.Exit(1)

    # Load universe config
    universe_obj = load_universe(universe_path)

    # Parse task arguments
    task_file_name = task_file
    task_ids = list(task_id) if task_id else []

    # Load tasks from specified file
    tasks_dir = universe_path / "tasks"
    if not tasks_dir.exists():
        console.print(f"[red]No tasks directory found in {universe_path}[/red]")
        raise typer.Exit(1)

    # Find the task file (try .yaml then .yml)
    task_file_path = tasks_dir / f"{task_file_name}.yaml"
    if not task_file_path.exists():
        task_file_path = tasks_dir / f"{task_file_name}.yml"
    if not task_file_path.exists():
        console.print(f"[red]Task file not found: {task_file_name}.yaml[/red]")
        available = [f.stem for f in tasks_dir.glob("*.yaml")] + [f.stem for f in tasks_dir.glob("*.yml")]
        console.print(f"[yellow]Available task files: {', '.join(available)}[/yellow]")
        raise typer.Exit(1)

    tasks = load_tasks(task_file_path)

    # Validate task compatibility with universe
    incompatible = [
        t for t in tasks
        if t.compatible_universes and universe_obj.name not in t.compatible_universes
    ]
    if incompatible:
        console.print(f"[red]Error: {len(incompatible)} tasks incompatible with universe '{universe_obj.name}'[/red]")
        console.print(f"[red]Incompatible task IDs: {[t.task_id for t in incompatible]}[/red]")
        raise typer.Exit(1)

    # Filter by task IDs if specified
    if task_ids:
        tasks = [t for t in tasks if t.task_id in task_ids]

    if limit:
        tasks = tasks[:limit]

    if not tasks:
        console.print("[red]No tasks to run[/red]")
        raise typer.Exit(1)

    zoo_config = ZooConfig(proxy_url=f"http://localhost:{proxy_port}")
    zoo = Zoo(zoo_config)
    if not zoo.is_running():
        console.print("[red]Zoo is not running.[/red]")
        console.print("Start your Zoo instance (dev: docker compose up, or package: npx the_zoo start)")
        raise typer.Exit(1)

    # Set up results database
    db = ResultsDB(db_path)

    # Format tasks info for storage
    tasks_info = task_file_name
    if task_ids:
        tasks_info += f":{','.join(str(t) for t in task_ids)}"

    # Validate and normalize autonomy levels first (needed for resume check)
    valid_levels = set(AUTONOMY_LEVELS)
    # Default to all levels if none specified
    if level is None:
        autonomy_levels = list(AUTONOMY_LEVELS)
    else:
        autonomy_levels = [lvl.upper() for lvl in level]
    invalid = set(autonomy_levels) - valid_levels
    if invalid:
        console.print(f"[red]Invalid autonomy level(s): {invalid}. Valid: {', '.join(AUTONOMY_LEVELS)}[/red]")
        raise typer.Exit(1)

    completed_pairs: set[tuple[int, str]] = set()

    if resume:
        run_id = db.get_latest_run(str(universe_path))
        if run_id:
            completed_pairs = db.get_completed_task_level_pairs(run_id)
            console.print(f"Resuming run #{run_id}: {len(completed_pairs)} (task, level) pairs already done")
        else:
            console.print("[yellow]No previous run found, starting fresh[/yellow]")
            run_id = db.create_run(
                config_path=str(universe_path),
                universe=universe_obj.name,
                model=model,
                tasks=tasks_info,
            )
    else:
        run_id = db.create_run(
            config_path=str(universe_path),
            universe=universe_obj.name,
            model=model,
            tasks=tasks_info,
        )

    # Check if all requested (task, level) pairs are already done
    requested_pairs = {(t.task_id, lvl) for t in tasks for lvl in autonomy_levels}
    remaining_pairs = requested_pairs - completed_pairs
    if not remaining_pairs:
        console.print("[green]All tasks already completed![/green]")
        print_report(db, run_id)
        db.close()
        return

    levels_str = ", ".join(autonomy_levels)
    model_info = claude_model if harness_enum == AgentHarness.CLAUDE_SDK else model

    # Create log directory for this run
    log_dir = create_log_dir("run", universe_obj.name, task_file_name)
    console.print(f"Logs: {log_dir}")

    console.print(f"Run #{run_id}: Running {len(tasks)} task(s) with harness={harness}, model={model_info}, levels=[{levels_str}]...")
    if completed_pairs:
        console.print(f"  ({len(remaining_pairs)} remaining, {len(completed_pairs)} already done)")

    run_config = RunConfig(
        headless=headless,
        max_steps=max_steps,
        timeout_seconds=timeout,
        model=model,
        judge_model=judge_model or "gpt-5.1",
        shared_browser=shared_browser,
        autonomy_levels=autonomy_levels,
        completed_pairs=completed_pairs,
        harness=harness_enum,
        claude_model=claude_model,
        use_proxy_events=use_proxy_events,
        redis_url=redis_url,
    )
    runner = TaskRunner(zoo, run_config, universe_path, universe_obj)

    # Initialize log file
    log_file = log_dir / "run.log"
    from datetime import datetime
    with open(log_file, "w") as f:
        f.write(f"Run #{run_id}\n")
        f.write(f"Universe: {universe_obj.name}\n")
        f.write(f"Task file: {task_file_name}\n")
        f.write(f"Model: {model_info}\n")
        f.write(f"Harness: {harness}\n")
        f.write(f"Levels: {levels_str}\n")
        f.write(f"Tasks: {len(tasks)}\n")
        f.write(f"Started: {datetime.now().isoformat()}\n")
        f.write("-" * 50 + "\n")
        f.flush()

    async def execute():
        await runner.setup()
        try:
            console.print(f"  Running {len(tasks)} task(s)...")

            # Run all tasks with agent assignment
            results = await runner.run_and_evaluate_batch(tasks, universe_obj.name)

            # Save and display results
            for result in results:
                db.save_result(run_id, result)
                score = result.score
                if score >= 1.0:
                    status = f"[green]{score:.2f}[/green]"
                elif score >= 0.5:
                    status = f"[yellow]{score:.2f}[/yellow]"
                else:
                    status = f"[red]{score:.2f}[/red]"
                level = result.task_result.autonomy_level
                subtasks = result.task_result.subtask_results
                subtask_info = f" ({sum(1 for s in subtasks if s.passed)}/{len(subtasks)})" if subtasks else ""
                console.print(
                    f"  Task {result.task.task_id} ({level}): {status}{subtask_info} ({result.task_result.duration_seconds:.1f}s)"
                )
                # Log to file in real-time
                with open(log_file, "a") as f:
                    status_char = "✓" if score >= 1.0 else "✗"
                    tr = result.task_result
                    f.write(f"{status_char} Task {result.task.task_id} ({level}): {score:.2f} | {tr.steps} steps | {tr.duration_seconds:.1f}s\n")
                    # Log agent details with full harness output
                    for ar in tr.agent_results:
                        f.write(f"  Agent {ar.agent_name}: {ar.steps} steps, {ar.duration_seconds:.1f}s\n")
                        if ar.answer:
                            f.write(f"    Final Answer:\n")
                            for line in ar.answer.split('\n'):
                                f.write(f"      {line}\n")
                        if ar.error:
                            f.write(f"    Error: {ar.error}\n")
                        # Extract and log full harness details
                        harness_details = _extract_harness_details(ar)
                        if harness_details:
                            f.write(f"    --- Harness Details ---\n")
                            for line in harness_details.split('\n'):
                                f.write(f"      {line}\n")
                    # Log subtask results with judge reasoning
                    if subtasks:
                        f.write(f"  --- Evaluation Results ---\n")
                        for sr in subtasks:
                            sr_status = "✓" if sr.passed else "✗"
                            f.write(f"  {sr_status} {sr.subtask_id}: {sr.description}\n")
                            if sr.evidence:
                                f.write(f"    Judge reasoning:\n")
                                for line in sr.evidence.split('\n'):
                                    f.write(f"      {line}\n")
                    if tr.error:
                        f.write(f"  Task Error: {tr.error}\n")
                    f.write("\n" + "-" * 60 + "\n")
                    f.flush()
        finally:
            await runner.teardown()

    asyncio.run(execute())

    # Finish run and show report
    db.finish_run(run_id)
    print_report(db, run_id)

    # Save run summary to log directory
    run_results = db.get_run_results(run_id)
    run_stats = db.get_run_stats(run_id)
    log_data = {
        "run_id": run_id,
        "universe": universe_obj.name,
        "task_file": task_file_name,
        "model": model_info,
        "harness": harness,
        "autonomy_levels": autonomy_levels,
        "stats": run_stats,
        "results": run_results,
    }
    with open(log_dir / "results.json", "w") as f:
        json.dump(log_data, f, indent=2)

    # Write final summary to log
    with open(log_file, "a") as f:
        f.write("\n" + "=" * 50 + "\n")
        f.write(f"Finished: {datetime.now().isoformat()}\n")
        f.write(f"Completed: {run_stats['completed']}/{run_stats['total']}\n")
        f.write(f"Score: {run_stats['avg_score']:.2f}\n")
        f.write(f"Completion rate: {run_stats['completion_rate']:.1f}%\n")
        f.flush()

    console.print(f"[green]Results saved to {log_dir}[/green]")

    db.close()


@app.command()
def report(
    run_id: int = typer.Argument(None, help="Run ID to report on (default: latest)"),
    db_path: Path = typer.Option("results.db", "--db", help="Results database path"),
    list_runs: bool = typer.Option(False, "--list", "-l", help="List all runs"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Show full evaluation reasoning"),
):
    """Show evaluation report."""
    db = ResultsDB(db_path)

    if list_runs:
        rows = db.conn.execute(
            "SELECT id, config_path, universe, model, tasks, started_at FROM runs ORDER BY id DESC LIMIT 20"
        ).fetchall()

        table = Table(title="Evaluation Runs")
        table.add_column("ID", style="cyan")
        table.add_column("Config")
        table.add_column("Universe")
        table.add_column("Model")
        table.add_column("Tasks", max_width=30)
        table.add_column("Started")

        for row in rows:
            tasks = row["tasks"]
            if tasks and len(tasks) > 30:
                tasks = tasks[:27] + "..."
            table.add_row(
                str(row["id"]),
                Path(row["config_path"]).name if row["config_path"] else "-",
                row["universe"] or "-",
                row["model"] or "-",
                tasks or "-",
                row["started_at"][:19] if row["started_at"] else "-",
            )
        console.print(table)
    else:
        if run_id is None:
            run_id = db.get_latest_run()
        if run_id is None:
            console.print("[red]No runs found[/red]")
            raise typer.Exit(1)

        print_report(db, run_id, detailed=detailed)

    db.close()


@app.command()
def reset():
    """Reset Zoo databases to initial state."""
    zoo = Zoo()
    console.print("Resetting databases...")
    if zoo.reset_databases():
        console.print("[green]Databases reset successfully[/green]")
    else:
        console.print("[red]Failed to reset databases[/red]")
        raise typer.Exit(1)


@app.command()
def postgres(
    query: str = typer.Argument(None, help="SQL query to execute"),
    database: str = typer.Option("postgres", "-d", "--database", help="Database name"),
    list_dbs: bool = typer.Option(False, "--list", "-l", help="List databases"),
    tables: bool = typer.Option(False, "--tables", "-t", help="List tables"),
):
    """Query PostgreSQL database."""
    zoo = Zoo()

    if list_dbs:
        console.print(zoo.list_postgres_databases())
    elif tables:
        console.print(zoo.list_postgres_tables(database))
    elif query:
        console.print(zoo.query_postgres(query, database))
    else:
        console.print("Provide a query or use --list / --tables")
        raise typer.Exit(1)


@app.command()
def mysql(
    query: str = typer.Argument(None, help="SQL query to execute"),
    database: str = typer.Option("mysql", "-d", "--database", help="Database name"),
    list_dbs: bool = typer.Option(False, "--list", "-l", help="List databases"),
    tables: bool = typer.Option(False, "--tables", "-t", help="List tables"),
):
    """Query MySQL database."""
    zoo = Zoo()

    if list_dbs:
        console.print(zoo.list_mysql_databases())
    elif tables:
        if database == "mysql":
            console.print("Specify a database with -d to list tables")
            raise typer.Exit(1)
        console.print(zoo.list_mysql_tables(database))
    elif query:
        console.print(zoo.query_mysql(query, database))
    else:
        console.print("Provide a query or use --list / --tables")
        raise typer.Exit(1)


@app.command()
def benchmark(
    universe: list[str] = typer.Option(None, "--universe", "-u", help="Universe(s) to run (default: all)"),
    multi_model: bool = typer.Option(False, "--multi-model", "-M", help="Run multi-model (heterogeneous) tasks only"),
    config_file: Path = typer.Option(None, "--config", "-c", help="YAML config file"),
    model: str = typer.Option("google/gemini-2.5-flash-lite", "--model", "-m", help="Agent model"),
    judge_model: str = typer.Option("gpt-5.1", "--judge-model", "-j", help="LLM judge model"),
    harness: str = typer.Option("browser_use", "--harness", "-H", help="Agent harness to use"),
    headless: bool = typer.Option(True, help="Run browser headlessly"),
    max_steps: int = typer.Option(30, help="Max steps per task"),
    timeout: int = typer.Option(120, help="Timeout in seconds per task"),
    level: list[str] = typer.Option(None, "--level", "-L", help="Autonomy level(s): L0, L1, L2"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Resume from last run"),
    proxy_port: int = typer.Option(3128, "--proxy-port", "-p", help="Zoo proxy port"),
):
    """Run benchmark suite across universes and tasks.

    By default runs all homogeneous (single-model) tasks in all universes.
    Use --universe/-u to filter to specific universe(s).
    Use --multi-model to run heterogeneous (multi-model) tasks instead.
    """
    # Load config from file or use CLI args
    if config_file and config_file.exists():
        config = BenchmarkConfig.from_yaml(config_file)
    else:
        config = BenchmarkConfig(
            model=model,
            judge_model=judge_model,
            harness=harness,
            headless=headless,
            max_steps=max_steps,
            timeout=timeout,
            autonomy_levels=level if level else list(AUTONOMY_LEVELS),
            proxy_port=proxy_port,
        )

    universes_filter = list(universe) if universe else None
    result = asyncio.run(run_benchmark(config, multi_model=multi_model, resume=resume, universes=universes_filter))
    if result is None:
        raise typer.Exit(1)


@app.command()
def create_universe(
    name: str = typer.Argument(..., help="Name of the new universe"),
    path: Path = typer.Option(
        None, "--path", "-p", help="Parent directory (default: pet_to_wild/universes)"
    ),
):
    """Create scaffolding for a new universe."""
    # Determine parent directory
    if path is None:
        parent = Path("pet_to_wild/universes")
    else:
        parent = Path(path)

    if not parent.exists():
        console.print(f"[red]Parent directory not found: {parent}[/red]")
        raise typer.Exit(1)

    universe_dir = parent / name
    if universe_dir.exists():
        console.print(f"[red]Universe already exists: {universe_dir}[/red]")
        raise typer.Exit(1)

    # Create directory structure
    universe_dir.mkdir()
    (universe_dir / "tasks").mkdir()
    (universe_dir / "scenes").mkdir()
    (universe_dir / "fixtures").mkdir()
    (universe_dir / "scripts").mkdir()  # For complex logic only
    (universe_dir / "custom_evaluators").mkdir()

    # Create __init__.py for Python package
    (universe_dir / "__init__.py").write_text("")

    # Create config.yaml
    config_content = f"""name: {name}
sites:
  - snappymail.zoo
  # Add more sites as needed: gitea.zoo, focalboard.zoo, wiki.zoo, etc.

services:
  snappymail.zoo:
    - stalwart
    - snappymail-zoo
  _core:
    - proxy
    - coredns
    - caddy
    - postgres
    - mysql
    - redis

agents:
  - role: user
    name: agent
    persona: ""
    goal: ""
"""
    (universe_dir / "config.yaml").write_text(config_content)

    # Create custom_evaluators/__init__.py
    evaluators_init = '''"""Custom evaluation functions for this universe.

Each function should:
- Accept a TaskResult as its only parameter
- Return an EvalResult

Example:
    from zoo_eval.evaluators import EvalResult
    from zoo_eval.models import EvalType, TaskResult

    def my_check(result: TaskResult) -> EvalResult:
        if "expected" in result.page_content:
            return EvalResult(passed=True, eval_type=EvalType.CUSTOM_FUNCTION, details="OK")
        return EvalResult(passed=False, eval_type=EvalType.CUSTOM_FUNCTION, details="Failed")
"""

__all__ = []
'''
    (universe_dir / "custom_evaluators" / "__init__.py").write_text(evaluators_init)

    # Create example task file
    example_task = f"""# Example task file for {name} universe
# See docs/benchmark_guide.md for full reference

- id: 1
  sites:
    - snappymail.zoo
  intent: "Example task description"
  start_url: "https://snappymail.zoo"
  compatible_universes:
    - {name}
  require_reset: false
  complexity: atomic
  environment: domesticated

  agents:
    agent:
      require_login: true
      autonomy_levels:
        L0: "Step-by-step instructions"
        L1: "Goal with method hint"
        L2: "Goal only"

  eval:
    types:
      - string_match
    answers:
      must_include:
        - expected_string
"""
    (universe_dir / "tasks" / "example.yaml").write_text(example_task)

    # Create example scene file
    example_scene = f"""# Example scene for {name} universe
# See docs/authoring-scenes.md for full reference

name: example_scene
description: "Example scene with email action"

setup:
  # Email action - credentials resolved from credentials/snappymail.zoo.yaml
  - type: email
    from: bob                    # Agent name from credentials file
    to: alice@snappymail.zoo
    subject: Test email
    body: |
      Hi Alice,
      This is a test email from the example scene.
      Best,
      Bob

  # For large content, use fixtures:
  # - type: gitea.file
  #   owner: bob
  #   repo: my-repo
  #   path: main.py
  #   content_file: fixtures/example_scene/main.py

# Triggered actions (run during task execution)
# actions:
#   - trigger:
#       type: request
#       url_contains: "gitea.zoo"
#       method: POST
#     type: email
#     from: bob
#     to: alice@snappymail.zoo
#     subject: Action triggered!
#     body: This email was sent when you made a POST to gitea.
"""
    (universe_dir / "scenes" / "example_scene.yaml").write_text(example_scene)

    console.print(f"[green]Created universe: {universe_dir}[/green]")
    console.print(f"  config.yaml        - Universe configuration")
    console.print(f"  tasks/             - Task YAML files (example.yaml included)")
    console.print(f"  scenes/            - Scene definitions (example_scene.yaml included)")
    console.print(f"  fixtures/          - Content files for scenes")
    console.print(f"  scripts/           - Complex logic scripts (use sparingly)")
    console.print(f"  custom_evaluators/ - Custom evaluation functions")


if __name__ == "__main__":
    app()
