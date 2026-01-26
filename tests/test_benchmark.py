"""Tests for benchmark.py module."""

import json
from dataclasses import asdict

import pytest

from zoo_eval.benchmark import (
    BenchmarkConfig,
    BenchmarkResults,
    TrialResult,
    generate_report,
)


class TestBenchmarkConfig:
    """Tests for BenchmarkConfig."""

    def test_total_runs_with_task_ids(self):
        """total_runs calculates correctly when task_ids are specified."""
        config = BenchmarkConfig(
            name="test",
            universe="test_universe",
            task_files=["email"],
            task_ids=[101, 102, 103],
            models=["model_a", "model_b"],
            harnesses=["browser_use"],
            autonomy_levels=["L1", "L2"],
            trials_per_config=3,
        )
        # 3 tasks * 2 models * 1 harness * 2 levels * 3 trials = 36
        assert config.total_runs() == 36

    def test_total_runs_without_task_ids(self):
        """total_runs returns None when task_ids not specified."""
        config = BenchmarkConfig(
            name="test",
            universe="test_universe",
            task_files=["email"],
            task_ids=None,
            models=["model_a"],
            harnesses=["browser_use"],
            autonomy_levels=["L1"],
        )
        assert config.total_runs() is None

    def test_total_runs_single_config(self):
        """total_runs works for single task/model/harness/level."""
        config = BenchmarkConfig(
            name="test",
            universe="test_universe",
            task_files=["email"],
            task_ids=[101],
            models=["model_a"],
            harnesses=["browser_use"],
            autonomy_levels=["L1"],
            trials_per_config=1,
        )
        assert config.total_runs() == 1

    def test_default_values(self):
        """Default values are set correctly."""
        config = BenchmarkConfig(
            name="test",
            universe="test_universe",
            task_files=["email"],
        )
        assert config.models == ["google/gemini-2.5-flash-lite"]
        assert config.harnesses == ["browser_use"]
        assert config.autonomy_levels == ["L1"]
        assert config.trials_per_config == 1
        assert config.max_steps == 30
        assert config.timeout_seconds == 120.0
        assert config.headless is True
        assert config.judge_model == "gpt-4o"


class TestTrialResult:
    """Tests for TrialResult dataclass."""

    def test_trial_result_creation(self):
        """TrialResult can be created with all fields."""
        result = TrialResult(
            task_id=101,
            model="model_a",
            harness="browser_use",
            autonomy_level="L1",
            trial=1,
            passed=True,
            steps=10,
            duration_seconds=30.5,
            error=None,
            cost_usd=0.05,
            eval_details="Passed all checks",
        )
        assert result.task_id == 101
        assert result.passed is True
        assert result.duration_seconds == 30.5

    def test_trial_result_with_error(self):
        """TrialResult correctly stores error information."""
        result = TrialResult(
            task_id=101,
            model="model_a",
            harness="browser_use",
            autonomy_level="L1",
            trial=1,
            passed=False,
            steps=5,
            duration_seconds=15.0,
            error="Timeout after 120s",
        )
        assert result.passed is False
        assert "Timeout" in result.error


class TestBenchmarkResults:
    """Tests for BenchmarkResults."""

    @pytest.fixture
    def sample_config(self):
        """Create a sample config for tests."""
        return BenchmarkConfig(
            name="test_benchmark",
            universe="test_universe",
            task_files=["email"],
            task_ids=[101, 102],
            models=["model_a", "model_b"],
            harnesses=["browser_use"],
            autonomy_levels=["L1", "L2"],
            trials_per_config=1,
        )

    @pytest.fixture
    def sample_trials(self):
        """Create sample trial results."""
        return [
            TrialResult(101, "model_a", "browser_use", "L1", 1, True, 10, 30.0),
            TrialResult(101, "model_a", "browser_use", "L2", 1, True, 8, 25.0),
            TrialResult(101, "model_b", "browser_use", "L1", 1, False, 15, 45.0),
            TrialResult(101, "model_b", "browser_use", "L2", 1, True, 12, 35.0),
            TrialResult(102, "model_a", "browser_use", "L1", 1, True, 9, 28.0),
            TrialResult(102, "model_a", "browser_use", "L2", 1, False, 20, 60.0),
            TrialResult(102, "model_b", "browser_use", "L1", 1, True, 11, 32.0),
            TrialResult(102, "model_b", "browser_use", "L2", 1, True, 10, 30.0),
        ]

    def test_summary_empty_trials(self, sample_config):
        """summary() returns empty dict when no trials."""
        results = BenchmarkResults(config=sample_config)
        assert results.summary() == {}

    def test_summary_overall_stats(self, sample_config, sample_trials):
        """summary() calculates overall statistics correctly."""
        results = BenchmarkResults(config=sample_config, trials=sample_trials)
        summary = results.summary()

        assert summary["total_trials"] == 8
        assert summary["passed"] == 6
        assert summary["failed"] == 2
        assert summary["pass_rate"] == 0.75

    def test_summary_by_model(self, sample_config, sample_trials):
        """summary() groups statistics by model."""
        results = BenchmarkResults(config=sample_config, trials=sample_trials)
        summary = results.summary()
        by_model = summary["by_model"]

        assert "model_a" in by_model
        assert "model_b" in by_model
        # model_a: 3 passed, 1 failed
        assert by_model["model_a"]["passed"] == 3
        assert by_model["model_a"]["failed"] == 1
        assert by_model["model_a"]["pass_rate"] == 0.75

    def test_summary_by_autonomy_level(self, sample_config, sample_trials):
        """summary() groups statistics by autonomy level."""
        results = BenchmarkResults(config=sample_config, trials=sample_trials)
        summary = results.summary()
        by_level = summary["by_autonomy_level"]

        assert "L1" in by_level
        assert "L2" in by_level
        # L1: 3 passed, 1 failed
        assert by_level["L1"]["passed"] == 3
        assert by_level["L1"]["pass_rate"] == 0.75

    def test_summary_by_task(self, sample_config, sample_trials):
        """summary() groups statistics by task ID."""
        results = BenchmarkResults(config=sample_config, trials=sample_trials)
        summary = results.summary()
        by_task = summary["by_task"]

        assert "101" in by_task
        assert "102" in by_task

    def test_summary_model_level_matrix(self, sample_config, sample_trials):
        """summary() creates model x level cross-tabulation."""
        results = BenchmarkResults(config=sample_config, trials=sample_trials)
        summary = results.summary()
        matrix = summary["model_level_matrix"]

        assert "model_a" in matrix
        assert "L1" in matrix["model_a"]
        assert "L2" in matrix["model_a"]
        assert "count" in matrix["model_a"]["L1"]
        assert "pass_rate" in matrix["model_a"]["L1"]
        assert "avg_steps" in matrix["model_a"]["L1"]

    def test_group_stats_std_steps_single_trial(self, sample_config):
        """_group_stats handles single trial (no stdev)."""
        trials = [
            TrialResult(101, "model_a", "browser_use", "L1", 1, True, 10, 30.0),
        ]
        results = BenchmarkResults(config=sample_config, trials=trials)
        summary = results.summary()

        # With single trial, std_steps should be 0
        assert summary["by_model"]["model_a"]["std_steps"] == 0

    def test_pass_rate_table(self, sample_config, sample_trials):
        """pass_rate_table() generates ASCII table."""
        results = BenchmarkResults(config=sample_config, trials=sample_trials)
        table = results.pass_rate_table()

        assert "Model" in table
        assert "L1" in table
        assert "L2" in table
        assert "model_a" in table
        assert "model_b" in table
        assert "%" in table

    def test_pass_rate_table_no_data(self, sample_config):
        """pass_rate_table() handles empty trials."""
        results = BenchmarkResults(config=sample_config)
        assert results.pass_rate_table() == "No data"

    def test_to_dict_json_roundtrip(self, sample_config, sample_trials):
        """to_dict() produces JSON-serializable output that preserves data."""
        results = BenchmarkResults(
            config=sample_config,
            trials=sample_trials,
            started_at="2024-01-01T10:00:00",
            finished_at="2024-01-01T10:05:00",
            total_duration_seconds=300.0,
        )
        result_dict = results.to_dict()

        # Check structure
        assert "config" in result_dict
        assert "trials" in result_dict
        assert "summary" in result_dict
        assert "started_at" in result_dict
        assert "finished_at" in result_dict

        # Verify JSON roundtrip preserves content
        json_str = json.dumps(result_dict)
        loaded = json.loads(json_str)

        assert loaded["config"]["name"] == "test_benchmark"
        assert len(loaded["trials"]) == 8
        assert loaded["summary"]["total_trials"] == 8
        assert loaded["summary"]["passed"] == 6
        assert loaded["started_at"] == "2024-01-01T10:00:00"


class TestGenerateReport:
    """Tests for report generation functions."""

    @pytest.fixture
    def sample_results(self):
        """Create sample results for report tests."""
        config = BenchmarkConfig(
            name="test_report",
            universe="test_universe",
            task_files=["email"],
            task_ids=[101],
            models=["model_a"],
            harnesses=["browser_use"],
            autonomy_levels=["L1"],
        )
        trials = [
            TrialResult(101, "model_a", "browser_use", "L1", 1, True, 10, 30.0),
        ]
        return BenchmarkResults(
            config=config,
            trials=trials,
            started_at="2024-01-01T10:00:00",
            finished_at="2024-01-01T10:00:30",
            total_duration_seconds=30.0,
        )

    def test_generate_text_report(self, sample_results):
        """generate_report produces valid text report."""
        report = generate_report(sample_results, format="text")

        assert "Benchmark Report: test_report" in report
        assert "Started:" in report
        assert "Finished:" in report
        assert "Duration:" in report
        assert "Total trials: 1" in report
        assert "Pass rate: 100.0%" in report
        assert "model_a" in report

    def test_generate_markdown_report(self, sample_results):
        """generate_report produces valid markdown report."""
        report = generate_report(sample_results, format="markdown")

        assert "# Benchmark Report: test_report" in report
        assert "## Overview" in report
        assert "## Configuration" in report
        assert "**Started:**" in report
        assert "| Model |" in report
        assert "| Task |" in report

    def test_generate_report_unknown_format(self, sample_results):
        """generate_report raises error for unknown format."""
        with pytest.raises(ValueError, match="Unknown format"):
            generate_report(sample_results, format="pdf")

    def test_text_report_empty_results(self):
        """Text report handles empty trials."""
        config = BenchmarkConfig(
            name="empty_test",
            universe="test_universe",
            task_files=["email"],
        )
        results = BenchmarkResults(config=config)
        report = generate_report(results, format="text")

        assert "empty_test" in report
        assert "Total trials: 0" in report

    def test_markdown_report_multiple_models(self):
        """Markdown report formats table correctly with multiple models."""
        config = BenchmarkConfig(
            name="multi_model",
            universe="test_universe",
            task_files=["email"],
            task_ids=[101],
            models=["model_a", "model_b"],
            harnesses=["browser_use"],
            autonomy_levels=["L1", "L2"],
        )
        trials = [
            TrialResult(101, "model_a", "browser_use", "L1", 1, True, 10, 30.0),
            TrialResult(101, "model_a", "browser_use", "L2", 1, False, 15, 45.0),
            TrialResult(101, "model_b", "browser_use", "L1", 1, True, 12, 35.0),
            TrialResult(101, "model_b", "browser_use", "L2", 1, True, 11, 32.0),
        ]
        results = BenchmarkResults(config=config, trials=trials)
        report = generate_report(results, format="markdown")

        # Check table structure
        assert "| Model | L1 | L2 |" in report
        assert "| model_a |" in report
        assert "| model_b |" in report
