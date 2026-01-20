#!/usr/bin/env python3
"""Audit script to verify db_match evaluations.

Runs all db_query definitions and shows the expected values for review.
Useful for validating that queries return correct expected answers.
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import yaml
from rich.console import Console
from rich.table import Table

from zoo_eval.models import load_tasks, EvalType
from zoo_eval.zoo import Zoo

console = Console()


def audit_db_evals(config_path: Path, task_ids: list[int] | None = None):
    """Run all db_query evals and show results."""
    tasks = load_tasks(config_path)
    zoo = Zoo()

    if not zoo.is_running():
        console.print("[red]Zoo is not running.[/red]")
        console.print("Start your Zoo instance (dev: docker compose up, or package: npx the_zoo start)")
        return

    # Filter to db_match tasks
    db_tasks = [
        t for t in tasks
        if EvalType.DB_MATCH in t.evaluation.eval_types and t.evaluation.db_query
    ]

    if task_ids:
        db_tasks = [t for t in db_tasks if t.task_id in task_ids]

    if not db_tasks:
        console.print("[yellow]No db_match tasks found[/yellow]")
        return

    console.print(f"\n[bold]Auditing {len(db_tasks)} db_match task(s)[/bold]\n")

    for task in db_tasks:
        db_query = task.evaluation.db_query
        console.print(f"[cyan]Task {task.task_id}:[/cyan] {task.intent[:60]}...")
        console.print(f"  [dim]Database:[/dim] {db_query.database} ({db_query.db_type})")
        console.print(f"  [dim]Match type:[/dim] {db_query.match_type}")
        console.print(f"  [dim]Query:[/dim]")
        for line in db_query.query.strip().split("\n"):
            console.print(f"    {line}")

        # Run the query
        try:
            if db_query.db_type == "mysql":
                result = zoo.query_mysql(db_query.query, db_query.database)
            else:
                result = zoo.query_postgres(db_query.query, db_query.database)

            # Parse and display results
            lines = result.strip().split("\n")
            if len(lines) >= 1:
                # Show as table
                headers = lines[0].split("\t")
                table = Table(title="Query Results")
                for h in headers:
                    table.add_column(h)

                for line in lines[1:]:
                    cols = line.split("\t")
                    table.add_row(*cols)

                console.print(table)

                # Extract expected values
                expected = [line.split("\t")[0].strip() for line in lines[1:]]
                console.print(f"  [green]Expected values ({len(expected)}):[/green] {expected}")

                # Compare with hardcoded if exists
                ref = task.evaluation.reference_answers
                if ref and ref.must_include:
                    hardcoded = set(ref.must_include)
                    from_db = set(expected)

                    if hardcoded == from_db:
                        console.print("  [green]Matches hardcoded values[/green]")
                    else:
                        console.print("  [red]MISMATCH with hardcoded values:[/red]")
                        only_hardcoded = hardcoded - from_db
                        only_db = from_db - hardcoded
                        if only_hardcoded:
                            console.print(f"    [red]In hardcoded but not DB:[/red] {only_hardcoded}")
                        if only_db:
                            console.print(f"    [yellow]In DB but not hardcoded:[/yellow] {only_db}")
            else:
                console.print("  [red]No results returned[/red]")

        except Exception as e:
            console.print(f"  [red]Error: {e}[/red]")

        console.print()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Audit db_match evaluations")
    parser.add_argument("config", type=Path, help="Path to tasks YAML file")
    parser.add_argument("--tasks", "-t", help="Comma-separated task IDs to audit")
    args = parser.parse_args()

    task_ids = None
    if args.tasks:
        task_ids = [int(x.strip()) for x in args.tasks.split(",")]

    audit_db_evals(args.config, task_ids)


if __name__ == "__main__":
    main()
