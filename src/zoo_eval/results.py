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
                config_path TEXT,
                universe TEXT,
                model TEXT,
                tasks TEXT,
                started_at TEXT,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS task_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                task_id INTEGER,
                task_name TEXT,
                autonomy_level TEXT DEFAULT 'L1',
                complexity TEXT,
                environment TEXT,
                score REAL DEFAULT 0.0,
                subtasks_passed INTEGER DEFAULT 0,
                subtasks_total INTEGER DEFAULT 0,
                agent_answer TEXT,
                final_url TEXT,
                error TEXT,
                steps INTEGER,
                duration_seconds REAL,
                created_at TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(id),
                UNIQUE(run_id, task_id, autonomy_level)
            );

            CREATE TABLE IF NOT EXISTS subtask_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_result_id INTEGER,
                subtask_id TEXT,
                description TEXT,
                weight INTEGER DEFAULT 1,
                passed INTEGER,
                evidence TEXT,
                eval_type TEXT,
                created_at TEXT,
                FOREIGN KEY (task_result_id) REFERENCES task_results(id)
            );

            CREATE TABLE IF NOT EXISTS agent_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_result_id INTEGER,
                agent_name TEXT,
                agent_role TEXT,
                answer TEXT,
                steps INTEGER,
                duration_seconds REAL,
                error TEXT,
                FOREIGN KEY (task_result_id) REFERENCES task_results(id)
            );

            CREATE INDEX IF NOT EXISTS idx_task_results_run_id ON task_results(run_id);
            CREATE INDEX IF NOT EXISTS idx_task_results_task_id ON task_results(task_id);
            CREATE INDEX IF NOT EXISTS idx_task_results_autonomy_level ON task_results(autonomy_level);
            CREATE INDEX IF NOT EXISTS idx_task_results_complexity ON task_results(complexity);
            CREATE INDEX IF NOT EXISTS idx_task_results_environment ON task_results(environment);
            CREATE INDEX IF NOT EXISTS idx_subtask_results_task_result_id ON subtask_results(task_result_id);
            CREATE INDEX IF NOT EXISTS idx_agent_results_task_result_id ON agent_results(task_result_id);
        """)
        self.conn.commit()

    def create_run(
        self,
        config_path: str | None = None,
        universe: str | None = None,
        model: str | None = None,
        tasks: str | None = None,
    ) -> int:
        """Create a new evaluation run and return its ID."""
        cursor = self.conn.execute(
            "INSERT INTO runs (config_path, universe, model, tasks, started_at) VALUES (?, ?, ?, ?, ?)",
            (config_path, universe, model, tasks, datetime.now().isoformat()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def finish_run(self, run_id: int):
        """Mark a run as finished."""
        self.conn.execute(
            "UPDATE runs SET finished_at = ? WHERE id = ?",
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
        """Get set of task IDs that have already been completed in a run.

        A task is considered complete only if all autonomy levels (L0, L1, L2)
        have been run, or if at least one result exists for old-format runs.
        """
        rows = self.conn.execute(
            """SELECT task_id, COUNT(DISTINCT autonomy_level) as level_count
               FROM task_results WHERE run_id = ?
               GROUP BY task_id""",
            (run_id,),
        ).fetchall()
        # Consider a task complete if it has all 3 autonomy levels done, or if
        # it's from an older run format (single result per task)
        return {row["task_id"] for row in rows if row["level_count"] >= 3 or row["level_count"] == 1}

    def get_completed_task_level_pairs(self, run_id: int) -> set[tuple[int, str]]:
        """Get set of (task_id, autonomy_level) pairs that have been completed."""
        rows = self.conn.execute(
            "SELECT task_id, autonomy_level FROM task_results WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return {(row["task_id"], row["autonomy_level"]) for row in rows}

    def save_result(self, run_id: int, result: RunResult):
        """Save a task result with subtasks and agent results."""
        task = result.task
        task_result = result.task_result

        # Compute subtask stats
        subtask_results = task_result.subtask_results
        subtasks_passed = sum(1 for s in subtask_results if s.passed)
        subtasks_total = len(subtask_results)

        # Insert main task result
        cursor = self.conn.execute(
            """INSERT OR REPLACE INTO task_results
               (run_id, task_id, task_name, autonomy_level, complexity, environment,
                score, subtasks_passed, subtasks_total, agent_answer, final_url,
                error, steps, duration_seconds, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                task.task_id,
                task.intent,  # Use intent as task name
                task_result.autonomy_level,
                task.complexity.value if task.complexity else None,
                task.environment.value if task.environment else None,
                task_result.score,
                subtasks_passed,
                subtasks_total,
                task_result.agent_answer,
                task_result.final_url,
                task_result.error,
                task_result.steps,
                task_result.duration_seconds,
                datetime.now().isoformat(),
            ),
        )
        task_result_id = cursor.lastrowid

        # Save subtask results
        for subtask in subtask_results:
            self.conn.execute(
                """INSERT INTO subtask_results
                   (task_result_id, subtask_id, description, weight, passed, evidence, eval_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_result_id,
                    subtask.subtask_id,
                    subtask.description,
                    subtask.weight,
                    1 if subtask.passed else 0,
                    subtask.evidence,
                    subtask.eval_type.value,
                    datetime.now().isoformat(),
                ),
            )

        # Save agent results
        for agent_result in task_result.agent_results:
            self.conn.execute(
                """INSERT INTO agent_results
                   (task_result_id, agent_name, agent_role, answer, steps, duration_seconds, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_result_id,
                    agent_result.agent_name,
                    agent_result.agent_role,
                    agent_result.answer,
                    agent_result.steps,
                    agent_result.duration_seconds,
                    agent_result.error,
                ),
            )

        self.conn.commit()

    def get_run_stats(self, run_id: int) -> dict[str, Any]:
        """Get statistics for a run."""
        row = self.conn.execute(
            """SELECT
                COUNT(*) as total,
                AVG(score) as avg_score,
                SUM(CASE WHEN score >= 1.0 THEN 1 ELSE 0 END) as completed,
                SUM(subtasks_passed) as total_subtasks_passed,
                SUM(subtasks_total) as total_subtasks,
                SUM(CASE WHEN error IS NOT NULL AND error != '' THEN 1 ELSE 0 END) as errors,
                AVG(duration_seconds) as avg_duration,
                SUM(duration_seconds) as total_duration,
                AVG(steps) as avg_steps
               FROM task_results WHERE run_id = ?""",
            (run_id,),
        ).fetchone()

        # Get per-autonomy-level stats
        level_stats = {}
        for level in ["L0", "L1", "L2"]:
            level_row = self.conn.execute(
                """SELECT
                    COUNT(*) as total,
                    AVG(score) as avg_score,
                    SUM(CASE WHEN score >= 1.0 THEN 1 ELSE 0 END) as completed
                   FROM task_results WHERE run_id = ? AND autonomy_level = ?""",
                (run_id, level),
            ).fetchone()
            level_total = level_row["total"] or 0
            level_stats[level] = {
                "total": level_total,
                "avg_score": level_row["avg_score"] or 0,
                "completed": level_row["completed"] or 0,
                "completion_rate": (level_row["completed"] or 0) / level_total * 100 if level_total else 0,
            }

        # Get per-environment stats
        env_stats = {}
        for env in ["domesticated", "tame", "wild"]:
            env_row = self.conn.execute(
                """SELECT
                    COUNT(*) as total,
                    AVG(score) as avg_score,
                    SUM(CASE WHEN score >= 1.0 THEN 1 ELSE 0 END) as completed
                   FROM task_results WHERE run_id = ? AND environment = ?""",
                (run_id, env),
            ).fetchone()
            env_total = env_row["total"] or 0
            if env_total > 0:
                env_stats[env] = {
                    "total": env_total,
                    "avg_score": env_row["avg_score"] or 0,
                    "completed": env_row["completed"] or 0,
                    "completion_rate": (env_row["completed"] or 0) / env_total * 100 if env_total else 0,
                }

        # Get per-complexity stats
        complexity_stats = {}
        for complexity in ["atomic", "compositional", "open_ended"]:
            comp_row = self.conn.execute(
                """SELECT
                    COUNT(*) as total,
                    AVG(score) as avg_score,
                    SUM(CASE WHEN score >= 1.0 THEN 1 ELSE 0 END) as completed
                   FROM task_results WHERE run_id = ? AND complexity = ?""",
                (run_id, complexity),
            ).fetchone()
            comp_total = comp_row["total"] or 0
            if comp_total > 0:
                complexity_stats[complexity] = {
                    "total": comp_total,
                    "avg_score": comp_row["avg_score"] or 0,
                    "completed": comp_row["completed"] or 0,
                    "completion_rate": (comp_row["completed"] or 0) / comp_total * 100 if comp_total else 0,
                }

        total = row["total"] or 0
        return {
            "total": total,
            "avg_score": row["avg_score"] or 0,
            "completed": row["completed"] or 0,
            "completion_rate": (row["completed"] or 0) / total * 100 if total else 0,
            "total_subtasks_passed": row["total_subtasks_passed"] or 0,
            "total_subtasks": row["total_subtasks"] or 0,
            "errors": row["errors"] or 0,
            "avg_duration": row["avg_duration"] or 0,
            "total_duration": row["total_duration"] or 0,
            "avg_steps": row["avg_steps"] or 0,
            "by_level": level_stats,
            "by_environment": env_stats,
            "by_complexity": complexity_stats,
        }

    def get_run_results(self, run_id: int) -> list[dict]:
        """Get all results for a run."""
        rows = self.conn.execute(
            """SELECT task_id, task_name, autonomy_level, complexity, environment,
                      score, subtasks_passed, subtasks_total, agent_answer, error,
                      steps, duration_seconds
               FROM task_results WHERE run_id = ? ORDER BY task_id, autonomy_level""",
            (run_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def get_subtask_results(self, task_result_id: int) -> list[dict]:
        """Get subtask results for a task result."""
        rows = self.conn.execute(
            """SELECT subtask_id, description, weight, passed, evidence, eval_type
               FROM subtask_results WHERE task_result_id = ? ORDER BY id""",
            (task_result_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_agent_results(self, task_result_id: int) -> list[dict]:
        """Get agent results for a task result."""
        rows = self.conn.execute(
            """SELECT agent_name, agent_role, answer, steps, duration_seconds, error
               FROM agent_results WHERE task_result_id = ? ORDER BY id""",
            (task_result_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_low_score_tasks(self, run_id: int, threshold: float = 1.0) -> list[dict]:
        """Get tasks with score below threshold."""
        rows = self.conn.execute(
            """SELECT id, task_id, task_name, autonomy_level, score, subtasks_passed,
                      subtasks_total, agent_answer, error
               FROM task_results WHERE run_id = ? AND score < ? ORDER BY score, task_id, autonomy_level""",
            (run_id, threshold),
        ).fetchall()

        return [dict(row) for row in rows]

    def close(self):
        """Close the database connection."""
        self.conn.close()


def _score_to_bar(score: float, width: int = 10) -> str:
    """Convert a 0-1 score to a progress bar."""
    filled = int(score * width)
    return "▓" * filled + "░" * (width - filled)


def _score_color(score: float) -> str:
    """Get color for a score."""
    if score >= 1.0:
        return "green"
    elif score >= 0.5:
        return "yellow"
    else:
        return "red"


def print_report(db: ResultsDB, run_id: int, detailed: bool = False):
    """Print a summary report for a run.

    Args:
        db: Database connection
        run_id: Run ID to report on
        detailed: If True, show subtask details for each task
    """
    from rich.console import Console
    from rich.table import Table

    console = Console()
    stats = db.get_run_stats(run_id)

    # Overall metrics
    console.print(f"\n[bold]═══ Run #{run_id} Summary ═══[/bold]")
    console.print(f"  Total tasks: {stats['total']}")
    console.print(f"  Avg score: [bold]{stats['avg_score']:.2f}[/bold]")
    console.print(f"  Completed (score=1.0): [green]{stats['completed']}[/green] ({stats['completion_rate']:.1f}%)")
    if stats['total_subtasks'] > 0:
        console.print(f"  Subtasks: {stats['total_subtasks_passed']}/{stats['total_subtasks']}")
    console.print(f"  Errors: {stats['errors']}")
    console.print(f"  Avg duration: {stats['avg_duration']:.1f}s | Total: {stats['total_duration']:.1f}s")

    # By environment
    if stats.get("by_environment"):
        console.print(f"\n[bold]By Environment:[/bold]")
        env_table = Table(show_header=True, header_style="bold")
        env_table.add_column("Environment")
        env_table.add_column("Avg Score")
        env_table.add_column("Completed")
        env_table.add_column("Total")

        for env in ["domesticated", "tame", "wild"]:
            env_data = stats["by_environment"].get(env, {})
            if env_data.get("total", 0) > 0:
                score = env_data.get("avg_score", 0)
                color = _score_color(score)
                env_table.add_row(
                    env.capitalize(),
                    f"[{color}]{score:.2f}[/{color}]",
                    str(env_data.get("completed", 0)),
                    str(env_data.get("total", 0)),
                )
        console.print(env_table)

    # By complexity
    if stats.get("by_complexity"):
        console.print(f"\n[bold]By Complexity:[/bold]")
        comp_table = Table(show_header=True, header_style="bold")
        comp_table.add_column("Complexity")
        comp_table.add_column("Avg Score")
        comp_table.add_column("Completed")
        comp_table.add_column("Total")

        for comp in ["atomic", "compositional", "open_ended"]:
            comp_data = stats["by_complexity"].get(comp, {})
            if comp_data.get("total", 0) > 0:
                score = comp_data.get("avg_score", 0)
                color = _score_color(score)
                comp_table.add_row(
                    comp.replace("_", " ").capitalize(),
                    f"[{color}]{score:.2f}[/{color}]",
                    str(comp_data.get("completed", 0)),
                    str(comp_data.get("total", 0)),
                )
        console.print(comp_table)

    # By autonomy level
    if stats.get("by_level"):
        console.print(f"\n[bold]By Autonomy Level:[/bold]")
        level_table = Table(show_header=True, header_style="bold")
        level_table.add_column("Level")
        level_table.add_column("Avg Score")
        level_table.add_column("Completed")
        level_table.add_column("Total")

        for level in ["L0", "L1", "L2"]:
            level_data = stats["by_level"].get(level, {})
            if level_data.get("total", 0) > 0:
                score = level_data.get("avg_score", 0)
                color = _score_color(score)
                level_table.add_row(
                    level,
                    f"[{color}]{score:.2f}[/{color}]",
                    str(level_data.get("completed", 0)),
                    str(level_data.get("total", 0)),
                )
        console.print(level_table)

    # Task results
    all_results = db.get_run_results(run_id)
    if all_results:
        # Group results by task_id
        tasks_by_id: dict[int, dict[str, dict]] = {}
        for row in all_results:
            task_id = row["task_id"]
            level = row.get("autonomy_level", "L1")
            if task_id not in tasks_by_id:
                tasks_by_id[task_id] = {}
            tasks_by_id[task_id][level] = row

        console.print(f"\n[bold]Task Scores:[/bold]")
        results_table = Table(show_header=True, header_style="bold")
        results_table.add_column("Task")
        results_table.add_column("L0")
        results_table.add_column("L1")
        results_table.add_column("L2")
        results_table.add_column("Progress")

        for task_id in sorted(tasks_by_id.keys()):
            levels = tasks_by_id[task_id]
            # Get best score for progress bar
            best_score = max((levels.get(l, {}).get("score", 0) for l in ["L0", "L1", "L2"]), default=0)
            row_data = [str(task_id)]

            for level in ["L0", "L1", "L2"]:
                if level not in levels:
                    row_data.append("-")
                    continue

                result = levels[level]
                score = result.get("score", 0)
                subtasks_passed = result.get("subtasks_passed", 0)
                subtasks_total = result.get("subtasks_total", 0)
                color = _score_color(score)

                if subtasks_total > 0:
                    row_data.append(f"[{color}]{score:.2f} ({subtasks_passed}/{subtasks_total})[/{color}]")
                else:
                    row_data.append(f"[{color}]{score:.2f}[/{color}]")

            row_data.append(_score_to_bar(best_score))
            results_table.add_row(*row_data)

        console.print(results_table)

        # Detailed subtask breakdown
        if detailed:
            console.print(f"\n[bold]═══ Detailed Results ═══[/bold]")
            for task_id in sorted(tasks_by_id.keys()):
                levels = tasks_by_id[task_id]
                for level in ["L0", "L1", "L2"]:
                    if level not in levels:
                        continue
                    result = levels[level]
                    score = result.get("score", 0)
                    color = _score_color(score)
                    task_name = result.get("task_name", "")[:50]

                    console.print(f"\n[bold]Task {task_id} ({level}):[/bold] [{color}]{score:.2f}[/{color}] {_score_to_bar(score)}")
                    if task_name:
                        console.print(f"  [dim]{task_name}[/dim]")

                    # Show subtasks if available (need task_result_id)
                    # For now show summary
                    subtasks_passed = result.get("subtasks_passed", 0)
                    subtasks_total = result.get("subtasks_total", 0)
                    if subtasks_total > 0:
                        console.print(f"  Subtasks: {subtasks_passed}/{subtasks_total}")

                    # Show error if present
                    if result.get("error"):
                        console.print(f"  [red]Error: {result['error']}[/red]")
        else:
            console.print(f"\n[dim]Use --detailed or -d to see subtask details[/dim]")
