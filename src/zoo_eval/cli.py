"""Command-line interface for zoo-eval."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .models import load_tasks
from .runner import RunConfig, TaskRunner
from .zoo import Zoo, ZooConfig

app = typer.Typer(
    help="Web agent evaluation harness using The Zoo",
    add_completion=False,
)
console = Console()


@app.command()
def status():
    """Check if Zoo is running and accessible."""
    zoo = Zoo()
    if zoo.is_running():
        console.print("[green]Zoo is running[/green]")
    else:
        console.print("[red]Zoo is not accessible[/red]")
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
    config: Path = typer.Argument(..., help="Path to tasks JSON file"),
    task_ids: str = typer.Option(None, "--tasks", "-t", help="Comma-separated task IDs"),
    limit: int = typer.Option(None, "--limit", "-n", help="Max tasks to run"),
    headless: bool = typer.Option(True, help="Run browser headlessly"),
    max_steps: int = typer.Option(50, help="Max steps per task"),
    output: Path = typer.Option(None, "--output", "-o", help="Output results to JSON"),
):
    """Run evaluation tasks."""
    tasks = load_tasks(config)

    # Filter by task IDs if specified
    if task_ids:
        ids = {int(i.strip()) for i in task_ids.split(",")}
        tasks = [t for t in tasks if t.task_id in ids]

    if limit:
        tasks = tasks[:limit]

    if not tasks:
        console.print("[red]No tasks to run[/red]")
        raise typer.Exit(1)

    console.print(f"Running {len(tasks)} task(s)...")

    zoo = Zoo()
    if not zoo.is_running():
        console.print("[red]Zoo is not running. Start it with: npx the_zoo start[/red]")
        raise typer.Exit(1)

    run_config = RunConfig(headless=headless, max_steps=max_steps)
    runner = TaskRunner(zoo, run_config)

    async def execute():
        await runner.setup()
        try:
            return await runner.run_batch(tasks)
        finally:
            await runner.teardown()

    results = asyncio.run(execute())

    # Display results
    table = Table(title="Results")
    table.add_column("Task ID", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Eval", style="yellow")
    table.add_column("Details", style="white", max_width=50)

    passed = 0
    for r in results:
        status = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        if r.passed:
            passed += 1

        eval_summary = ", ".join(
            f"{'✓' if e.passed else '✗'} {e.eval_type.value}" for e in r.eval_results
        )
        details = r.eval_results[0].details if r.eval_results else r.task_result.error or ""

        table.add_row(str(r.task.task_id), status, eval_summary, details[:50])

    console.print(table)
    console.print(f"\n[bold]Total: {passed}/{len(results)} passed[/bold]")

    # Save results if output specified
    if output:
        output_data = [
            {
                "task_id": r.task.task_id,
                "passed": r.passed,
                "success": r.task_result.success,
                "agent_answer": r.task_result.agent_answer,
                "final_url": r.task_result.final_url,
                "error": r.task_result.error,
                "steps": r.task_result.steps,
                "duration": r.task_result.duration_seconds,
                "evaluations": [
                    {"type": e.eval_type.value, "passed": e.passed, "details": e.details}
                    for e in r.eval_results
                ],
            }
            for r in results
        ]
        output.write_text(json.dumps(output_data, indent=2))
        console.print(f"Results saved to {output}")


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


if __name__ == "__main__":
    app()
