"""Tests for the CLI eval command."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from typer.testing import CliRunner

from zoo_eval.cli import app
from zoo_eval.results import ResultsDB


runner = CliRunner()


@pytest.fixture
def temp_db():
    """Create a temporary database with test data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = ResultsDB(db_path)

    # Create a test run
    run_id = db.create_run(
        config_path="test/universe",
        universe="test",
        model="test-model",
        tasks="coordination:301",
    )

    # Insert a test result
    db.conn.execute(
        """INSERT INTO task_results
           (run_id, task_id, autonomy_level, success, passed, agent_answer,
            final_url, error, steps, duration_seconds, eval_results, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            301,
            "L1",
            1,
            0,  # passed=False (we'll re-evaluate)
            "[alice]: Email sent to bob. [SIGNAL: complete]\n[bob]: Confirmed Wednesday 11am. [SIGNAL: complete]",
            "https://snappymail.zoo",
            None,
            10,
            60.0,
            json.dumps([{"type": "llm_judge", "passed": False, "details": "old result"}]),
            "2024-01-01T00:00:00",
        ),
    )
    db.conn.commit()
    db.close()

    yield db_path, run_id

    # Cleanup
    db_path.unlink(missing_ok=True)


@pytest.fixture
def mock_universe(tmp_path):
    """Create a mock universe directory with task config."""
    universe_dir = tmp_path / "test_universe"
    universe_dir.mkdir()
    tasks_dir = universe_dir / "tasks"
    tasks_dir.mkdir()

    # Create config.yaml
    (universe_dir / "config.yaml").write_text("""
name: test
sites:
  - mail
agents: []
services: {}
""")

    # Create task file
    (tasks_dir / "coordination.yaml").write_text("""
tasks:
  - id: 301
    sites:
      - mail
    intent: "Test meeting negotiation"
    start_url: "https://snappymail.zoo"
    agents:
      alice:
        require_login: true
        username: alice@snappymail.zoo
        password: alice123
        autonomy_levels:
          L1: "Send email"
      bob:
        require_login: true
        username: bob@snappymail.zoo
        password: bob123
        autonomy_levels:
          L1: "Reply to email"
    eval:
      types:
        - custom_function
      custom_function: "pet_to_wild.universes.startup.custom_evaluators.coordination_checker.verify_meeting_negotiated"
""")

    return universe_dir


class TestEvalCommand:
    """Tests for the eval CLI command."""

    def test_eval_help(self):
        """Eval command shows help."""
        result = runner.invoke(app, ["eval", "--help"])
        assert result.exit_code == 0
        assert "Re-run evaluation" in result.output

    def test_eval_no_universe(self):
        """Eval command fails if universe not found."""
        result = runner.invoke(app, ["eval", "nonexistent", "-t", "coordination"])
        assert result.exit_code == 1
        assert "Universe not found" in result.output

    def test_eval_no_task_file(self, mock_universe):
        """Eval command fails if task file not found."""
        result = runner.invoke(app, ["eval", str(mock_universe), "-t", "nonexistent"])
        assert result.exit_code == 1
        assert "Task file not found" in result.output

    def test_eval_no_db(self, mock_universe, tmp_path):
        """Eval command fails if no runs in database."""
        empty_db = tmp_path / "empty.db"
        result = runner.invoke(app, [
            "eval", str(mock_universe), "-t", "coordination",
            "--db", str(empty_db)
        ])
        assert result.exit_code == 1
        assert "No runs found" in result.output

    @patch("zoo_eval.evaluators.evaluate_task")
    def test_eval_runs_evaluator(self, mock_evaluate, mock_universe, temp_db):
        """Eval command runs evaluation on stored results."""
        from zoo_eval.evaluators import EvalResult
        from zoo_eval.models import EvalType

        db_path, run_id = temp_db

        # Mock the evaluator as async
        async def mock_eval(*args, **kwargs):
            return [EvalResult(passed=True, eval_type=EvalType.CUSTOM_FUNCTION, details="Test passed")]
        mock_evaluate.side_effect = mock_eval

        result = runner.invoke(app, [
            "eval", str(mock_universe), "-t", "coordination",
            "--db", str(db_path), "--run", str(run_id)
        ])

        assert result.exit_code == 0
        assert "Evaluating 1 result" in result.output
        assert mock_evaluate.called

    @patch("zoo_eval.evaluators.evaluate_task")
    def test_eval_update_db(self, mock_evaluate, mock_universe, temp_db):
        """Eval command updates database when --update is used."""
        from zoo_eval.evaluators import EvalResult
        from zoo_eval.models import EvalType

        db_path, run_id = temp_db

        # Mock the evaluator as async
        async def mock_eval(*args, **kwargs):
            return [EvalResult(passed=True, eval_type=EvalType.CUSTOM_FUNCTION, details="Now passing")]
        mock_evaluate.side_effect = mock_eval

        result = runner.invoke(app, [
            "eval", str(mock_universe), "-t", "coordination",
            "--db", str(db_path), "--run", str(run_id), "--update"
        ])

        assert result.exit_code == 0
        assert "Database updated" in result.output

        # Verify database was updated
        db = ResultsDB(db_path)
        results = db.get_run_results(run_id)
        db.close()

        assert len(results) == 1
        assert results[0]["passed"] == 1  # Now passing

    def test_eval_filter_by_task_id(self, mock_universe, temp_db):
        """Eval command filters by task ID."""
        db_path, run_id = temp_db

        # Filter to task 999 which doesn't exist
        result = runner.invoke(app, [
            "eval", str(mock_universe), "-t", "coordination",
            "--db", str(db_path), "-i", "999"
        ])

        assert result.exit_code == 1
        assert "No matching results" in result.output

    def test_eval_filter_by_level(self, mock_universe, temp_db):
        """Eval command filters by autonomy level."""
        db_path, run_id = temp_db

        # Filter to L0 which doesn't exist in our test data
        result = runner.invoke(app, [
            "eval", str(mock_universe), "-t", "coordination",
            "--db", str(db_path), "-L", "L0"
        ])

        assert result.exit_code == 1
        assert "No matching results" in result.output


class TestEvalCommandIntegration:
    """Integration tests for eval command with real evaluators."""

    @patch("pet_to_wild.universes.startup.custom_evaluators.coordination_checker.get_email_headers")
    @patch("pet_to_wild.universes.startup.custom_evaluators.coordination_checker.get_email_body")
    @patch("pet_to_wild.universes.startup.custom_evaluators.coordination_checker.search_emails")
    def test_eval_with_imap_checker(self, mock_search, mock_body, mock_headers, mock_universe, temp_db):
        """Test eval command with IMAP-based coordination checker."""
        db_path, run_id = temp_db

        # Update task file to use IMAP checker with agent contexts
        tasks_dir = mock_universe / "tasks"
        (tasks_dir / "coordination.yaml").write_text("""
tasks:
  - id: 301
    sites:
      - mail
    intent: "Test meeting negotiation"
    start_url: "https://snappymail.zoo"
    agents:
      alice:
        context: |
          Calendar: Monday 9am-12pm, Wednesday 10am-3pm
        autonomy_levels:
          L1: "Send email"
      bob:
        context: |
          Calendar: Wednesday all day
        autonomy_levels:
          L1: "Reply"
    eval:
      types:
        - custom_function
      custom_function: "pet_to_wild.universes.startup.custom_evaluators.coordination_checker.verify_meeting_negotiated_with_imap"
""")

        # Mock IMAP to return emails found
        mock_search.return_value = [1]  # Return UID list
        mock_headers.return_value = {"Subject": "Meeting proposal"}
        mock_body.return_value = "Let's meet Wednesday at 11am"

        # Also mock the LLM call
        with patch("zoo_eval.llm.create_openai_client") as mock_llm:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = '{"agreed_time": "Wednesday 11am", "valid_for_all": true, "passed": true, "reasoning": "Time works for both"}'
            mock_client.chat.completions.create.return_value = mock_response
            mock_llm.return_value = (mock_client, "gpt-4o")

            result = runner.invoke(app, [
                "eval", str(mock_universe), "-t", "coordination",
                "--db", str(db_path)
            ])

        # Should run without error and show IMAP verification passed
        assert result.exit_code == 0
        assert "IMAP Verification" in result.output
        assert "Alice→Bob" in result.output
