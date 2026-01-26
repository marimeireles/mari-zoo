"""Tests for zoo_eval.scenes module."""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, mock_open
from pathlib import Path
import tempfile
import os

from zoo_eval.scenes import SceneManager, get_default_project
from zoo_eval.models import Scene, Trigger, ActionPayload


@pytest.fixture
def mock_zoo():
    """Create a mock Zoo instance."""
    return MagicMock()


@pytest.fixture
def temp_universe(tmp_path):
    """Create a temporary universe directory with a scene."""
    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir()

    # Create a test scene file
    scene_yaml = """
name: test_scene
description: A test scene
setup:
  - type: script
    script_path: scripts/setup.py
triggers:
  - type: time
    delay: 5
actions:
  - type: script
    script_path: scripts/action.py
"""
    (scenes_dir / "test_scene.yaml").write_text(scene_yaml)

    # Create scripts directory
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    # Create a simple test script
    (scripts_dir / "setup.py").write_text("print('setup ran')")
    (scripts_dir / "action.py").write_text("print('action ran')")

    return tmp_path


class TestGetDefaultProject:
    """Tests for get_default_project function."""

    def test_returns_env_var_if_set(self):
        """Returns ZOO_COMPOSE_PROJECT_NAME if set."""
        with patch.dict(os.environ, {"ZOO_COMPOSE_PROJECT_NAME": "my_project"}):
            assert get_default_project() == "my_project"

    def test_returns_fallback_when_no_containers(self):
        """Returns default when no containers running."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists
            os.environ.pop("ZOO_COMPOSE_PROJECT_NAME", None)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                assert get_default_project() == "the_zoo"


class TestSceneManagerInit:
    """Tests for SceneManager initialization."""

    def test_init_with_zoo(self, mock_zoo):
        """SceneManager initializes with Zoo instance."""
        manager = SceneManager(mock_zoo)
        assert manager.zoo == mock_zoo
        assert manager.universe_path is None
        assert manager.active_tasks == []
        assert manager.actions_log == []

    def test_init_with_universe_path(self, mock_zoo, tmp_path):
        """SceneManager initializes with universe path."""
        manager = SceneManager(mock_zoo, universe_path=tmp_path)
        assert manager.universe_path == tmp_path


class TestSceneManagerLoadAndActivate:
    """Tests for SceneManager.load_and_activate_scene()."""

    @pytest.mark.asyncio
    async def test_requires_universe_path(self, mock_zoo):
        """Raises error if universe_path not set."""
        manager = SceneManager(mock_zoo)

        with pytest.raises(ValueError, match="universe_path must be set"):
            await manager.load_and_activate_scene("test_scene", 0.0)

    @pytest.mark.asyncio
    async def test_raises_if_scene_not_found(self, mock_zoo, tmp_path):
        """Raises FileNotFoundError if scene doesn't exist."""
        scenes_dir = tmp_path / "scenes"
        scenes_dir.mkdir()

        manager = SceneManager(mock_zoo, universe_path=tmp_path)

        with pytest.raises(FileNotFoundError, match="Scene file not found"):
            await manager.load_and_activate_scene("nonexistent", 0.0)

    @pytest.mark.asyncio
    async def test_loads_and_returns_scene(self, mock_zoo, temp_universe):
        """Successfully loads scene from file."""
        manager = SceneManager(mock_zoo, universe_path=temp_universe)

        # Mock _run_actions to avoid actually running scripts
        manager._run_actions = AsyncMock()

        scene = await manager.load_and_activate_scene("test_scene", 0.0)

        assert scene.name == "test_scene"
        assert scene.description == "A test scene"
        assert len(scene.triggers) == 1

    @pytest.mark.asyncio
    async def test_runs_setup_actions(self, mock_zoo, temp_universe):
        """Runs setup actions when loading scene."""
        manager = SceneManager(mock_zoo, universe_path=temp_universe)
        manager._run_actions = AsyncMock()

        await manager.load_and_activate_scene("test_scene", 0.0)

        # Setup should be called exactly once
        calls = manager._run_actions.call_args_list
        assert len(calls) == 1, f"Expected setup to run exactly once, got {len(calls)} calls"
        # Check setup was called with label
        first_call = calls[0]
        assert first_call.args[1] == "setup script"


class TestSceneManagerActivateScene:
    """Tests for SceneManager.activate_scene()."""

    @pytest.mark.asyncio
    async def test_time_trigger_delay_zero_runs_immediately(self, mock_zoo):
        """Time trigger with delay=0 runs actions immediately."""
        manager = SceneManager(mock_zoo)
        manager._run_actions = AsyncMock()

        trigger = Trigger(trigger_type="time", delay=0)
        action = ActionPayload(action_type="script", script_path="test.py")
        scene = Scene(name="test", triggers=[trigger], actions=[action])

        await manager.activate_scene(scene, 0.0)

        # Should have been called immediately
        manager._run_actions.assert_called_once()

    @pytest.mark.asyncio
    async def test_time_trigger_with_delay_schedules_task(self, mock_zoo):
        """Time trigger with delay > 0 schedules async task."""
        manager = SceneManager(mock_zoo)
        manager._run_actions = AsyncMock()

        trigger = Trigger(trigger_type="time", delay=10)
        action = ActionPayload(action_type="script", script_path="test.py")
        scene = Scene(name="test", triggers=[trigger], actions=[action])

        await manager.activate_scene(scene, 0.0)

        # Should have scheduled a task
        assert len(manager.active_tasks) == 1
        # Actions not run yet
        manager._run_actions.assert_not_called()

        # Clean up
        await manager.cleanup()

    @pytest.mark.asyncio
    async def test_page_load_trigger_runs_immediately(self, mock_zoo):
        """Page load trigger runs actions immediately."""
        manager = SceneManager(mock_zoo)
        manager._run_actions = AsyncMock()

        trigger = Trigger(trigger_type="page_load")
        action = ActionPayload(action_type="script", script_path="test.py")
        scene = Scene(name="test", triggers=[trigger], actions=[action])

        await manager.activate_scene(scene, 0.0)

        manager._run_actions.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_trigger_schedules_polling_task(self, mock_zoo):
        """Event trigger schedules Matomo polling task."""
        manager = SceneManager(mock_zoo)
        manager._run_actions = AsyncMock()

        trigger = Trigger(
            trigger_type="event",
            site="gitea.zoo",
            event_category="AJAX",
            event_match="/pulls",
            timeout=10.0,
        )
        action = ActionPayload(action_type="script", script_path="test.py")
        scene = Scene(name="test", triggers=[trigger], actions=[action])

        await manager.activate_scene(scene, 0.0)

        # Should have scheduled a polling task
        assert len(manager.active_tasks) == 1

        # Clean up
        await manager.cleanup()


class TestSceneManagerTimeTrigger:
    """Tests for _schedule_time_trigger."""

    @pytest.mark.asyncio
    async def test_waits_for_delay(self, mock_zoo):
        """Time trigger waits for specified delay."""
        manager = SceneManager(mock_zoo)
        manager._run_actions = AsyncMock()

        trigger = Trigger(trigger_type="time", delay=0.1)
        action = ActionPayload(action_type="script", script_path="test.py")
        scene = Scene(name="test", triggers=[trigger], actions=[action])

        # Run trigger directly
        await manager._schedule_time_trigger(trigger, scene)

        manager._run_actions.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_delay_returns_early(self, mock_zoo):
        """Time trigger with None delay returns without action."""
        manager = SceneManager(mock_zoo)
        manager._run_actions = AsyncMock()

        trigger = Trigger(trigger_type="time", delay=None)
        scene = Scene(name="test", triggers=[], actions=[])

        await manager._schedule_time_trigger(trigger, scene)

        manager._run_actions.assert_not_called()


class TestSceneManagerEventTrigger:
    """Tests for _schedule_event_trigger."""

    @pytest.mark.asyncio
    async def test_missing_site_returns_early(self, mock_zoo):
        """Event trigger without site returns early."""
        manager = SceneManager(mock_zoo)
        manager._run_actions = AsyncMock()

        trigger = Trigger(
            trigger_type="event",
            site=None,
            event_match="/pulls",
        )
        scene = Scene(name="test", triggers=[], actions=[])

        await manager._schedule_event_trigger(trigger, scene)

        manager._run_actions.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_event_match_returns_early(self, mock_zoo):
        """Event trigger without event_match returns early."""
        manager = SceneManager(mock_zoo)
        manager._run_actions = AsyncMock()

        trigger = Trigger(
            trigger_type="event",
            site="gitea.zoo",
            event_match=None,
        )
        scene = Scene(name="test", triggers=[], actions=[])

        await manager._schedule_event_trigger(trigger, scene)

        manager._run_actions.assert_not_called()

    @pytest.mark.asyncio
    async def test_runs_action_when_event_found(self, mock_zoo):
        """Runs actions when Matomo event is found."""
        manager = SceneManager(mock_zoo)
        manager._run_actions = AsyncMock()

        trigger = Trigger(
            trigger_type="event",
            site="gitea.zoo",
            event_category="AJAX",
            event_match="/pulls",
            timeout=10.0,
        )
        action = ActionPayload(action_type="script", script_path="test.py")
        scene = Scene(name="test", triggers=[], actions=[action])

        # Mock Matomo client to return an event
        mock_event = MagicMock()
        mock_event.category = "AJAX"
        mock_event.name = "/pulls/create"

        with patch("zoo_eval.scenes.get_matomo_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.find_event.return_value = mock_event
            mock_get_client.return_value = mock_client

            await manager._schedule_event_trigger(trigger, scene, poll_interval=0.01)

        manager._run_actions.assert_called_once()

    @pytest.mark.asyncio
    async def test_times_out_when_no_event(self, mock_zoo):
        """Times out if no matching event found."""
        manager = SceneManager(mock_zoo)
        manager._run_actions = AsyncMock()

        trigger = Trigger(
            trigger_type="event",
            site="gitea.zoo",
            event_match="/pulls",
            timeout=0.05,  # Very short timeout for test
        )
        scene = Scene(name="test", triggers=[], actions=[])

        with patch("zoo_eval.scenes.get_matomo_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.find_event.return_value = None  # No event found
            mock_get_client.return_value = mock_client

            await manager._schedule_event_trigger(trigger, scene, poll_interval=0.01)

        # Should not run actions on timeout
        manager._run_actions.assert_not_called()


class TestSceneManagerRunScript:
    """Tests for _run_script."""

    @pytest.mark.asyncio
    async def test_logs_error_for_missing_script_path(self, mock_zoo):
        """Logs error when script_path is empty."""
        manager = SceneManager(mock_zoo)
        action = ActionPayload(action_type="script", script_path="")

        await manager._run_script(action)

        assert len(manager.actions_log) == 1
        assert manager.actions_log[0]["success"] is False
        assert "No script_path" in manager.actions_log[0]["error"]

    @pytest.mark.asyncio
    async def test_runs_script_successfully(self, mock_zoo, tmp_path):
        """Successfully runs a Python script."""
        manager = SceneManager(mock_zoo, universe_path=tmp_path)

        # Create a test script
        script = tmp_path / "test_script.py"
        script.write_text("print('hello')")

        action = ActionPayload(action_type="script", script_path=str(script))

        await manager._run_script(action)

        assert len(manager.actions_log) == 1
        assert manager.actions_log[0]["success"] is True

    @pytest.mark.asyncio
    async def test_logs_script_failure(self, mock_zoo, tmp_path):
        """Logs error when script fails."""
        manager = SceneManager(mock_zoo, universe_path=tmp_path)

        # Create a script that fails
        script = tmp_path / "failing_script.py"
        script.write_text("import sys; sys.exit(1)")

        action = ActionPayload(action_type="script", script_path=str(script))

        await manager._run_script(action)

        assert len(manager.actions_log) == 1
        assert manager.actions_log[0]["success"] is False

    @pytest.mark.asyncio
    async def test_resolves_relative_path(self, mock_zoo, tmp_path):
        """Resolves relative script paths from universe directory."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script = scripts_dir / "test.py"
        script.write_text("print('relative')")

        manager = SceneManager(mock_zoo, universe_path=tmp_path)
        action = ActionPayload(action_type="script", script_path="scripts/test.py")

        await manager._run_script(action)

        assert len(manager.actions_log) == 1
        assert manager.actions_log[0]["success"] is True


class TestSceneManagerCleanup:
    """Tests for cleanup method."""

    @pytest.mark.asyncio
    async def test_cancels_active_tasks(self, mock_zoo):
        """Cleanup cancels all active tasks."""
        manager = SceneManager(mock_zoo)

        # Create some fake tasks
        async def long_running():
            await asyncio.sleep(100)

        task1 = asyncio.create_task(long_running())
        task2 = asyncio.create_task(long_running())
        manager.active_tasks = [task1, task2]

        await manager.cleanup()

        # Wait for cancellation to complete
        await asyncio.sleep(0.01)

        assert task1.cancelled()
        assert task2.cancelled()
        assert manager.active_tasks == []


class TestSceneManagerActionLock:
    """Tests for action lock preventing concurrent execution."""

    @pytest.mark.asyncio
    async def test_actions_run_sequentially(self, mock_zoo):
        """Action lock ensures sequential execution."""
        manager = SceneManager(mock_zoo)

        execution_order = []

        async def track_action(action):
            execution_order.append(f"start_{action.script_path}")
            await asyncio.sleep(0.01)
            execution_order.append(f"end_{action.script_path}")

        # Patch _run_script to track execution
        original_run_script = manager._run_script
        manager._run_script = track_action

        action1 = ActionPayload(action_type="script", script_path="1")
        action2 = ActionPayload(action_type="script", script_path="2")

        # Run two action batches concurrently
        await asyncio.gather(
            manager._run_actions([action1]),
            manager._run_actions([action2]),
        )

        # Because of lock, actions should not interleave
        # One should complete before the other starts
        # Valid orders: [start_1, end_1, start_2, end_2] or [start_2, end_2, start_1, end_1]
        assert execution_order in [
            ["start_1", "end_1", "start_2", "end_2"],
            ["start_2", "end_2", "start_1", "end_1"],
        ], f"Actions interleaved unexpectedly: {execution_order}"
