"""Command-line interface for zoo-eval."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .models import RunConfig, load_tasks, load_universe
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
    task: list[str] = typer.Option(..., "--task", "-t", help="Task file name and optional ID: --task devtools or --task devtools 201"),
    limit: int = typer.Option(None, "--limit", "-n", help="Max tasks to run"),
    headless: bool = typer.Option(True, help="Run browser headlessly"),
    max_steps: int = typer.Option(30, help="Max steps per task"),
    timeout: int = typer.Option(120, help="Timeout in seconds per task"),
    model: str = typer.Option("google/gemini-2.5-flash-lite", "--model", "-m", help="Model: flash, flash-lite, claude, gpt-4o, or provider/model"),
    shared_browser: bool = typer.Option(False, "--shared-browser", help="All agents share same browser and memory"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Resume from last run"),
    db_path: Path = typer.Option("results.db", "--db", help="Results database path"),
    proxy_port: int = typer.Option(3128, "--proxy-port", "-p", help="Zoo proxy port"),
    seed: Path = typer.Option(None, "--seed", help="Path to seed script to run before tasks"),
):
    """Run evaluation tasks from a universe directory."""
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

    # Parse --task argument: first element is filename, rest are optional task IDs
    task_file_name = task[0]
    task_ids = [int(t) for t in task[1:]] if len(task) > 1 else []

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

    # Run seed script if provided (after Zoo is verified running)
    if seed:
        import subprocess
        # Resolve seed path relative to universe directory if not absolute
        seed_path = Path(seed)
        if not seed_path.is_absolute():
            seed_path = universe_path / seed_path
        console.print(f"[cyan]Running seed script: {seed_path}[/cyan]")
        try:
            result = subprocess.run(["python3", str(seed_path)], capture_output=True, text=True, timeout=300)
            if result.stdout:
                console.print(result.stdout)
            if result.stderr:
                console.print(f"[red]{result.stderr}[/red]")
            if result.returncode != 0:
                console.print(f"[red]Seed script failed (exit code {result.returncode})[/red]")
                raise typer.Exit(1)
            console.print("[green]✓ Seed script completed[/green]")
        except subprocess.TimeoutExpired:
            console.print("[red]Seed script timeout[/red]")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[red]Seed script error: {e}[/red]")
            raise typer.Exit(1)

    # Set up results database
    db = ResultsDB(db_path)

    # Format tasks info for storage
    tasks_info = task_file_name
    if task_ids:
        tasks_info += f":{','.join(str(t) for t in task_ids)}"

    if resume:
        run_id = db.get_latest_run(str(universe_path))
        if run_id:
            completed = db.get_completed_task_ids(run_id)
            original_count = len(tasks)
            tasks = [t for t in tasks if t.task_id not in completed]
            console.print(f"Resuming run #{run_id}: {len(completed)} already done, {len(tasks)} remaining")
        else:
            console.print("[yellow]No previous run found, starting fresh[/yellow]")
            run_id = db.create_run(
                config_path=str(universe_path),
                universe=universe_obj.name,
                seed_script=str(seed) if seed else None,
                model=model,
                tasks=tasks_info,
            )
    else:
        run_id = db.create_run(
            config_path=str(universe_path),
            universe=universe_obj.name,
            seed_script=str(seed) if seed else None,
            model=model,
            tasks=tasks_info,
        )

    if not tasks:
        console.print("[green]All tasks already completed![/green]")
        print_report(db, run_id)
        db.close()
        return

    console.print(f"Run #{run_id}: Running {len(tasks)} task(s) with model={model}...")

    run_config = RunConfig(
        headless=headless,
        max_steps=max_steps,
        timeout_seconds=timeout,
        model=model,
        shared_browser=shared_browser,
    )
    runner = TaskRunner(zoo, run_config, universe_path)

    async def execute():
        await runner.setup()
        try:
            console.print(f"  Running {len(tasks)} task(s)...")

            # Run all tasks with agent assignment
            results = await runner.run_and_evaluate_batch(tasks, universe_obj.name)

            # Save and display results
            for result in results:
                db.save_result(run_id, result)
                status = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
                level = result.task_result.autonomy_level
                console.print(
                    f"  Task {result.task.task_id} ({level}): {status} ({result.task_result.duration_seconds:.1f}s)"
                )
        finally:
            await runner.teardown()

    asyncio.run(execute())

    # Finish run and show report
    db.finish_run(run_id)
    print_report(db, run_id)
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
            "SELECT id, config_path, universe, seed_script, model, tasks, started_at FROM runs ORDER BY id DESC LIMIT 20"
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


if __name__ == "__main__":
    app()
