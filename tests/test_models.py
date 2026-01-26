"""Tests for zoo_eval.models parsing and validation."""

import pytest
from zoo_eval.models import (
    AgentHarness,
    Task,
    TaskAgentConfig,
    Evaluation,
    EvalType,
    Trigger,
    ReferenceAnswers,
    HTMLCheck,
    DBQuery,
    Scene,
    ActionPayload,
    TaskComplexity,
    Environment,
    RunConfig,
)


class TestTaskParsing:
    """Tests for Task.from_dict()"""

    def test_valid_task_minimal(self):
        """Parse a minimal valid task."""
        data = {
            "id": 1,
            "intent": "Test task",
            "agents": {
                "alice": {"require_login": False}
            }
        }
        task = Task.from_dict(data)
        assert task.task_id == 1
        assert task.intent == "Test task"
        assert "alice" in task.agents

    def test_valid_task_full(self):
        """Parse a fully specified task."""
        data = {
            "id": 101,
            "sites": ["mail", "gitea"],
            "intent": "Send an email and create a PR",
            "start_url": "https://snappymail.zoo",
            "compatible_universes": ["startup"],
            "require_reset": True,
            "complexity": "compositional",
            "environment": "tame",
            "scene": "email_injection",
            "agents": {
                "alice": {
                    "require_login": True,
                    "username": "alice@test.zoo",
                    "password": "secret123",
                    "autonomy_levels": {
                        "L0": "Step by step instructions",
                        "L1": "Goal with method",
                        "L2": "Just the goal"
                    }
                }
            },
            "eval": {
                "types": ["string_match"],
                "answers": {"must_include": ["success"]}
            }
        }
        task = Task.from_dict(data)
        assert task.task_id == 101
        assert task.sites == ["mail", "gitea"]
        assert task.complexity == TaskComplexity.COMPOSITIONAL
        assert task.environment == Environment.TAME
        assert task.scene_name == "email_injection"
        assert task.require_reset is True
        assert task.agents["alice"].username == "alice@test.zoo"
        assert task.agents["alice"].autonomy_levels["L1"] == "Goal with method"

    def test_task_id_from_task_id_field(self):
        """Support legacy 'task_id' field name."""
        data = {
            "task_id": 42,
            "intent": "Legacy format",
            "agents": {"bob": {}}
        }
        task = Task.from_dict(data)
        assert task.task_id == 42

    def test_missing_id_raises(self):
        """Missing task ID should raise ValueError."""
        data = {
            "intent": "No ID task",
            "agents": {"alice": {}}
        }
        with pytest.raises(ValueError, match="missing required field.*id"):
            Task.from_dict(data)

    def test_missing_intent_raises(self):
        """Missing intent should raise ValueError."""
        data = {
            "id": 1,
            "agents": {"alice": {}}
        }
        with pytest.raises(ValueError, match="missing required field.*intent"):
            Task.from_dict(data)

    def test_missing_agents_raises(self):
        """Missing agents should raise ValueError."""
        data = {
            "id": 1,
            "intent": "No agents"
        }
        with pytest.raises(ValueError, match="no agents defined"):
            Task.from_dict(data)

    def test_empty_agents_raises(self):
        """Empty agents dict should raise ValueError."""
        data = {
            "id": 1,
            "intent": "Empty agents",
            "agents": {}
        }
        with pytest.raises(ValueError, match="no agents defined"):
            Task.from_dict(data)

    def test_invalid_complexity_raises(self):
        """Invalid complexity value should raise ValueError."""
        data = {
            "id": 1,
            "intent": "Bad complexity",
            "complexity": "super_hard",
            "agents": {"alice": {}}
        }
        with pytest.raises(ValueError, match="invalid complexity"):
            Task.from_dict(data)

    def test_invalid_environment_raises(self):
        """Invalid environment value should raise ValueError."""
        data = {
            "id": 1,
            "intent": "Bad environment",
            "environment": "hostile",
            "agents": {"alice": {}}
        }
        with pytest.raises(ValueError, match="invalid environment"):
            Task.from_dict(data)


class TestEvaluationParsing:
    """Tests for Evaluation.from_dict()"""

    def test_valid_string_match(self):
        """Parse string_match evaluation."""
        data = {
            "types": ["string_match"],
            "answers": {
                "exact_match": "hello world",
                "must_include": ["hello", "world"]
            }
        }
        eval = Evaluation.from_dict(data)
        assert EvalType.STRING_MATCH in eval.eval_types
        assert eval.reference_answers.exact_match == "hello world"
        assert eval.reference_answers.must_include == ["hello", "world"]

    def test_valid_url_match(self):
        """Parse url_match evaluation."""
        data = {
            "types": ["url_match"],
            "url": "https://example.zoo/success"
        }
        eval = Evaluation.from_dict(data)
        assert EvalType.URL_MATCH in eval.eval_types
        assert eval.reference_url == "https://example.zoo/success"

    def test_valid_db_match(self):
        """Parse db_match evaluation."""
        data = {
            "types": ["db_match"],
            "db_query": {
                "database": "testdb",
                "query": "SELECT * FROM users",
                "type": "postgres",
                "match_type": "exact_match"
            }
        }
        eval = Evaluation.from_dict(data)
        assert EvalType.DB_MATCH in eval.eval_types
        assert eval.db_query.database == "testdb"
        assert eval.db_query.db_type == "postgres"

    def test_valid_llm_judge(self):
        """Parse llm_judge evaluation."""
        data = {
            "types": ["llm_judge"],
            "llm_judge_criteria": [
                "The response is helpful",
                "The response is accurate"
            ]
        }
        eval = Evaluation.from_dict(data)
        assert EvalType.LLM_JUDGE in eval.eval_types
        assert len(eval.llm_judge_criteria) == 2

    def test_valid_custom_function(self):
        """Parse custom_function evaluation."""
        data = {
            "types": ["custom_function"],
            "custom_function": "my_module.my_checker"
        }
        eval = Evaluation.from_dict(data)
        assert EvalType.CUSTOM_FUNCTION in eval.eval_types
        assert eval.custom_function == "my_module.my_checker"

    def test_multiple_eval_types(self):
        """Parse evaluation with multiple types."""
        data = {
            "types": ["string_match", "url_match", "llm_judge"],
            "answers": {"must_include": ["test"]},
            "url": "https://test.zoo",
            "llm_judge_criteria": ["Is correct"]
        }
        eval = Evaluation.from_dict(data)
        assert len(eval.eval_types) == 3

    def test_invalid_eval_type_raises(self):
        """Invalid eval type should raise ValueError."""
        data = {
            "types": ["invalid_type"]
        }
        with pytest.raises(ValueError, match="Invalid eval type"):
            Evaluation.from_dict(data)

    def test_empty_types_ok(self):
        """Empty types list is allowed."""
        data = {"types": []}
        eval = Evaluation.from_dict(data)
        assert eval.eval_types == []


class TestTriggerParsing:
    """Tests for Trigger.from_dict()"""

    def test_time_trigger(self):
        """Parse time-based trigger."""
        data = {
            "type": "time",
            "delay": 30
        }
        trigger = Trigger.from_dict(data)
        assert trigger.trigger_type == "time"
        assert trigger.delay == 30

    def test_event_trigger(self):
        """Parse event-based trigger."""
        data = {
            "type": "event",
            "site": "gitea.zoo",
            "event_category": "AJAX",
            "event_match": "/pulls"
        }
        trigger = Trigger.from_dict(data)
        assert trigger.trigger_type == "event"
        assert trigger.site == "gitea.zoo"
        assert trigger.event_category == "AJAX"
        assert trigger.event_match == "/pulls"

    def test_page_load_trigger(self):
        """Parse page_load trigger."""
        data = {"type": "page_load"}
        trigger = Trigger.from_dict(data)
        assert trigger.trigger_type == "page_load"

    def test_trigger_timeout_default(self):
        """Trigger should have default 600s timeout."""
        data = {"type": "event", "site": "test.zoo", "event_match": "test"}
        trigger = Trigger.from_dict(data)
        assert trigger.timeout == 600.0

    def test_trigger_timeout_custom(self):
        """Trigger can have custom timeout."""
        data = {
            "type": "event",
            "site": "test.zoo",
            "event_match": "test",
            "timeout": 120.0
        }
        trigger = Trigger.from_dict(data)
        assert trigger.timeout == 120.0


class TestReferenceAnswersParsing:
    """Tests for ReferenceAnswers.from_dict()"""

    def test_exact_match(self):
        """Parse exact_match answer."""
        data = {"exact_match": "hello"}
        answers = ReferenceAnswers.from_dict(data)
        assert answers.exact_match == "hello"
        assert answers.must_include == []

    def test_must_include(self):
        """Parse must_include answers."""
        data = {"must_include": ["foo", "bar"]}
        answers = ReferenceAnswers.from_dict(data)
        assert answers.must_include == ["foo", "bar"]

    def test_both_fields(self):
        """Parse both exact_match and must_include."""
        data = {
            "exact_match": "exact",
            "must_include": ["a", "b"]
        }
        answers = ReferenceAnswers.from_dict(data)
        assert answers.exact_match == "exact"
        assert answers.must_include == ["a", "b"]

    def test_none_input(self):
        """None input should return None."""
        assert ReferenceAnswers.from_dict(None) is None

    def test_empty_dict(self):
        """Empty dict should return None."""
        assert ReferenceAnswers.from_dict({}) is None


class TestHTMLCheckParsing:
    """Tests for HTMLCheck.from_dict()"""

    def test_basic_check(self):
        """Parse basic HTML check."""
        data = {
            "url": "https://test.zoo/page",
            "locator": "#main-content",
            "required_contents": {"text": ["hello", "world"]}
        }
        check = HTMLCheck.from_dict(data)
        assert check.url == "https://test.zoo/page"
        assert check.locator == "#main-content"
        assert check.required_contents["text"] == ["hello", "world"]

    def test_defaults(self):
        """Check default values."""
        data = {}
        check = HTMLCheck.from_dict(data)
        assert check.url == "last"
        assert check.locator == ""
        assert check.required_contents == {}


class TestDBQueryParsing:
    """Tests for DBQuery.from_dict()"""

    def test_mysql_query(self):
        """Parse MySQL query."""
        data = {
            "database": "mydb",
            "query": "SELECT * FROM users",
            "type": "mysql",
            "match_type": "must_include"
        }
        query = DBQuery.from_dict(data)
        assert query.database == "mydb"
        assert query.db_type == "mysql"
        assert query.match_type == "must_include"

    def test_postgres_query(self):
        """Parse PostgreSQL query."""
        data = {
            "database": "pgdb",
            "query": "SELECT count(*) FROM items",
            "type": "postgres",
            "match_type": "count"
        }
        query = DBQuery.from_dict(data)
        assert query.db_type == "postgres"
        assert query.match_type == "count"

    def test_defaults(self):
        """Check default values."""
        data = {"database": "db", "query": "SELECT 1"}
        query = DBQuery.from_dict(data)
        assert query.db_type == "mysql"
        assert query.match_type == "must_include"

    def test_none_input(self):
        """None input should return None."""
        assert DBQuery.from_dict(None) is None


class TestSceneParsing:
    """Tests for Scene.from_dict()"""

    def test_basic_scene(self):
        """Parse basic scene."""
        data = {
            "name": "test_scene",
            "description": "A test scene"
        }
        scene = Scene.from_dict(data)
        assert scene.name == "test_scene"
        assert scene.description == "A test scene"
        assert scene.setup == []
        assert scene.triggers == []
        assert scene.actions == []

    def test_scene_with_setup(self):
        """Parse scene with setup actions."""
        data = {
            "name": "seeded_scene",
            "setup": [
                {"type": "script", "script_path": "scripts/seed.py"}
            ]
        }
        scene = Scene.from_dict(data)
        assert len(scene.setup) == 1
        assert scene.setup[0].script_path == "scripts/seed.py"

    def test_scene_with_triggers_and_actions(self):
        """Parse scene with triggers and actions."""
        data = {
            "name": "reactive_scene",
            "triggers": [
                {"type": "event", "site": "gitea.zoo", "event_match": "/pulls"}
            ],
            "actions": [
                {"type": "script", "script_path": "scripts/react.py"}
            ]
        }
        scene = Scene.from_dict(data)
        assert len(scene.triggers) == 1
        assert scene.triggers[0].trigger_type == "event"
        assert len(scene.actions) == 1

    def test_none_input(self):
        """None input should return None."""
        assert Scene.from_dict(None) is None


class TestTaskAgentConfigParsing:
    """Tests for TaskAgentConfig.from_dict()"""

    def test_minimal_agent(self):
        """Parse minimal agent config."""
        config = TaskAgentConfig.from_dict("alice", {})
        assert config.name == "alice"
        assert config.require_login is False
        assert config.username is None

    def test_full_agent(self):
        """Parse full agent config."""
        data = {
            "require_login": True,
            "username": "alice@test.zoo",
            "password": "secret",
            "autonomy_levels": {
                "L0": "Detailed steps",
                "L1": "Brief steps",
                "L2": "Goal only"
            }
        }
        config = TaskAgentConfig.from_dict("alice", data)
        assert config.require_login is True
        assert config.username == "alice@test.zoo"
        assert config.password == "secret"
        assert len(config.autonomy_levels) == 3


class TestAgentHarness:
    """Tests for AgentHarness enum."""

    def test_browser_use_value(self):
        """Browser use harness has correct value."""
        assert AgentHarness.BROWSER_USE.value == "browser_use"

    def test_claude_sdk_value(self):
        """Claude SDK harness has correct value."""
        assert AgentHarness.CLAUDE_SDK.value == "claude_sdk"

    def test_harness_from_string(self):
        """Can create harness from string value."""
        assert AgentHarness("browser_use") == AgentHarness.BROWSER_USE
        assert AgentHarness("claude_sdk") == AgentHarness.CLAUDE_SDK


class TestRunConfig:
    """Tests for RunConfig dataclass."""

    def test_defaults(self):
        """Test default values."""
        config = RunConfig()
        assert config.max_steps == 30
        assert config.timeout_seconds == 120.0
        assert config.headless is True
        assert config.harness == AgentHarness.BROWSER_USE
        assert config.autonomy_levels == ["L1"]
        assert config.completed_pairs == set()

    def test_custom_values(self):
        """Test custom configuration."""
        config = RunConfig(
            max_steps=50,
            timeout_seconds=300.0,
            headless=False,
            harness=AgentHarness.CLAUDE_SDK,
            autonomy_levels=["L0", "L1", "L2"],
            model="anthropic/claude-sonnet-4",
            judge_model="gpt-4o",
            claude_model="opus",
        )
        assert config.max_steps == 50
        assert config.timeout_seconds == 300.0
        assert config.headless is False
        assert config.harness == AgentHarness.CLAUDE_SDK
        assert config.autonomy_levels == ["L0", "L1", "L2"]
        assert config.claude_model == "opus"

    def test_completed_pairs_is_set(self):
        """completed_pairs should be a set for O(1) lookup."""
        config = RunConfig()
        config.completed_pairs.add((1, "L0"))
        config.completed_pairs.add((1, "L1"))
        assert (1, "L0") in config.completed_pairs
        assert (1, "L1") in config.completed_pairs
        assert (1, "L2") not in config.completed_pairs

    def test_skip_zoo_reset_default_false(self):
        """skip_zoo_reset should default to False."""
        config = RunConfig()
        assert config.skip_zoo_reset is False

    def test_skip_zoo_reset_can_be_set(self):
        """skip_zoo_reset can be set to True."""
        config = RunConfig(skip_zoo_reset=True)
        assert config.skip_zoo_reset is True
