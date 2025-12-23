"""Results storage and reporting with SQLite."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import TaskResult
from .evaluators import EvalResult
from .runner import RunResult


DEFAULT_DB_PATH = Path("./results.db")


class ResultsDB:
    """SQLite-based results storage for resumable evaluations."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                config_path TEXT,
                started_at TEXT,
                finished_at TEXT,
                status TEXT DEFAULT 'running'
            );

            CREATE TABLE IF NOT EXISTS task_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                task_id INTEGER,
                success INTEGER,
                passed INTEGER,
                agent_answer TEXT,
                final_url TEXT,
                error TEXT,
                steps INTEGER,
                duration_seconds REAL,
                eval_results TEXT,
                created_at TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(id),
                UNIQUE(run_id, task_id)
            );

            CREATE INDEX IF NOT EXISTS idx_task_results_run_id ON task_results(run_id);
            CREATE INDEX IF NOT EXISTS idx_task_results_task_id ON task_results(task_id);
        """)
        self.conn.commit()

    def create_run(self, name: str | None = None, config_path: str | None = None) -> int:
        """Create a new evaluation run and return its ID."""
        cursor = self.conn.execute(
            "INSERT INTO runs (name, config_path, started_at) VALUES (?, ?, ?)",
            (name, config_path, datetime.now().isoformat()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def finish_run(self, run_id: int):
        """Mark a run as finished."""
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, status = 'finished' WHERE id = ?",
            (datetime.now().isoformat(), run_id),
        )
        self.conn.commit()

    def get_latest_run(self, config_path: str | None = None) -> int | None:
        """Get the latest run ID, optionally filtered by config path."""
        if config_path:
            row = self.conn.execute(
                "SELECT id FROM runs WHERE config_path = ? ORDER BY id DESC LIMIT 1",
                (config_path,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT id FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return row["id"] if row else None

    def get_completed_task_ids(self, run_id: int) -> set[int]:
        """Get set of task IDs that have already been completed in a run."""
        rows = self.conn.execute(
            "SELECT task_id FROM task_results WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return {row["task_id"] for row in rows}

    def save_result(self, run_id: int, result: RunResult):
        """Save a single task result."""
        eval_results_json = json.dumps([
            {"type": e.eval_type.value, "passed": e.passed, "details": e.details}
            for e in result.eval_results
        ])

        self.conn.execute(
            """INSERT OR REPLACE INTO task_results
               (run_id, task_id, success, passed, agent_answer, final_url,
                error, steps, duration_seconds, eval_results, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                result.task.task_id,
                1 if result.task_result.success else 0,
                1 if result.passed else 0,
                result.task_result.agent_answer,
                result.task_result.final_url,
                result.task_result.error,
                result.task_result.steps,
                result.task_result.duration_seconds,
                eval_results_json,
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()

    def get_run_stats(self, run_id: int) -> dict[str, Any]:
        """Get statistics for a run."""
        row = self.conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(passed) as passed,
                SUM(success) as success,
                SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as errors,
                AVG(duration_seconds) as avg_duration,
                SUM(duration_seconds) as total_duration,
                AVG(steps) as avg_steps
               FROM task_results WHERE run_id = ?""",
            (run_id,),
        ).fetchone()

        return {
            "total": row["total"] or 0,
            "passed": row["passed"] or 0,
            "failed": (row["total"] or 0) - (row["passed"] or 0),
            "success_rate": (row["passed"] or 0) / row["total"] * 100 if row["total"] else 0,
            "errors": row["errors"] or 0,
            "avg_duration": row["avg_duration"] or 0,
            "total_duration": row["total_duration"] or 0,
            "avg_steps": row["avg_steps"] or 0,
        }

    def get_run_results(self, run_id: int) -> list[dict]:
        """Get all results for a run."""
        rows = self.conn.execute(
            """SELECT task_id, success, passed, agent_answer, error,
                      steps, duration_seconds, eval_results
               FROM task_results WHERE run_id = ? ORDER BY task_id""",
            (run_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def get_failed_tasks(self, run_id: int) -> list[dict]:
        """Get failed task details for a run."""
        rows = self.conn.execute(
            """SELECT task_id, agent_answer, error, eval_results
               FROM task_results WHERE run_id = ? AND passed = 0 ORDER BY task_id""",
            (run_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def close(self):
        """Close the database connection."""
        self.conn.close()


def print_report(db: ResultsDB, run_id: int):
    """Print a summary report for a run."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    stats = db.get_run_stats(run_id)

    console.print(f"\n[bold]Run #{run_id} Summary[/bold]")
    console.print(f"  Total tasks: {stats['total']}")
    console.print(f"  Passed: [green]{stats['passed']}[/green]")
    console.print(f"  Failed: [red]{stats['failed']}[/red]")
    console.print(f"  Success rate: [bold]{stats['success_rate']:.1f}%[/bold]")
    console.print(f"  Errors: {stats['errors']}")
    console.print(f"  Avg duration: {stats['avg_duration']:.1f}s")
    console.print(f"  Total duration: {stats['total_duration']:.1f}s")
    console.print(f"  Avg steps: {stats['avg_steps']:.1f}")

    # Show failed tasks
    failed = db.get_failed_tasks(run_id)
    if failed:
        console.print(f"\n[bold red]Failed Tasks ({len(failed)}):[/bold red]")

        for row in failed[:10]:  # Show first 10
            console.print(f"\n  [cyan]Task {row['task_id']}:[/cyan]")

            # Show agent answer
            if row["agent_answer"]:
                answer = row["agent_answer"][:200]
                if len(row["agent_answer"]) > 200:
                    answer += "..."
                console.print(f"    [dim]Agent answered:[/dim] {answer}")

            # Show error or eval failure reason
            reason = row["error"] or ""
            if not reason and row["eval_results"]:
                evals = json.loads(row["eval_results"])
                for e in evals:
                    if not e["passed"]:
                        reason = e["details"]
                        break
            console.print(f"    [red]Reason:[/red] {reason[:100]}")

        if len(failed) > 10:
            console.print(f"\n  ... and {len(failed) - 10} more")
