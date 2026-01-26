"""Scene management for benchmark scenarios."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .models import Scene, Trigger, ActionPayload, AgentTrigger, load_scene
from .matomo import get_matomo_client

if TYPE_CHECKING:
    from .zoo import Zoo


def get_default_project() -> str:
    """Get the default Zoo project name from running containers or environment."""
    # First check environment variable
    env_project = os.environ.get("ZOO_COMPOSE_PROJECT_NAME")
    if env_project:
        return env_project

    # Try to detect from running containers
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}", "--filter", "name=zoo"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            # Extract project name from first container (e.g., "thezoo-cli-instance-default-v0-7-0-proxy-1")
            first_container = result.stdout.strip().split("\n")[0]
            # Project name is everything before the last service name
            parts = first_container.rsplit("-", 2)
            if len(parts) >= 2:
                return "-".join(parts[:-2])  # Remove service name and replica number
    except Exception:
        pass

    # Fallback to common default
    return "the_zoo"



class SceneManager:
    """Manages scene activation and verification."""

    def __init__(self, zoo: Zoo, universe_path: Path | None = None):
        self.zoo = zoo
        self.universe_path = universe_path
        self.active_tasks: list[asyncio.Task] = []
        self.start_time: float | None = None
        self.actions_log: list[dict] = []  # Track all actions for verification
        self._action_lock = asyncio.Lock()  # Prevent concurrent action execution
        self._scene: Scene | None = None  # Current active scene

    def get_agent_triggers(self) -> list[AgentTrigger]:
        """Get agent triggers from the active scene."""
        if self._scene is None:
            return []
        return self._scene.agents

    async def wait_for_agent_start(self, agent_name: str) -> bool:
        """Wait until the given agent should start.

        Args:
            agent_name: Name of the agent (must match task agent config)

        Returns:
            True when agent should start, False if trigger timed out
        """
        if self._scene is None:
            return True  # No scene = start immediately

        # Check if this agent has a trigger in the scene
        for agent_trigger in self._scene.agents:
            if agent_trigger.name == agent_name:
                return await self.wait_for_trigger(agent_trigger.trigger)

        # No trigger for this agent = start immediately
        return True

    async def load_and_activate_scene(
        self, scene_name: str, task_start_time: float
    ) -> Scene:
        """
        Load a scene from file and activate it.

        Args:
            scene_name: Name of the scene file (without .yaml extension)
            task_start_time: Timestamp when the task started
        """
        # Scenes directory is inside the universe
        if self.universe_path is None:
            raise ValueError("universe_path must be set to load scenes")

        scenes_dir = self.universe_path / "scenes"
        scene_path = scenes_dir / f"{scene_name}.yaml"
        if not scene_path.exists():
            raise FileNotFoundError(f"Scene file not found: {scene_path}")

        scene = load_scene(scene_path)
        self._scene = scene  # Store for agent trigger queries

        # Run setup actions first (before task starts)
        await self._run_actions(scene.setup, "setup script")

        # Then activate triggers for runtime actions
        await self.activate_scene(scene, task_start_time)
        return scene

    async def _run_actions(self, actions: list[ActionPayload], label: str = ""):
        """Run a list of actions.

        Uses a lock to prevent concurrent execution when multiple agents
        trigger the same scene action simultaneously.
        """
        async with self._action_lock:
            for action in actions:
                if action.action_type == "script":
                    if label:
                        print(f"Running {label}: {action.script_path}")
                    await self._run_script(action)

    async def activate_scene(self, scene: Scene, task_start_time: float):
        """
        Activate scene based on per-action triggers.

        Args:
            scene: Scene to activate
            task_start_time: Timestamp when the task started (for time-based triggers)
        """
        self.start_time = task_start_time

        # Each action has its own trigger
        for action in scene.actions:
            if action.trigger is None:
                # No trigger = run immediately
                await self._run_single_action(action)
            elif action.trigger.trigger_type == "time":
                if action.trigger.delay == 0:
                    await self._run_single_action(action)
                else:
                    task = asyncio.create_task(self._schedule_action(action))
                    self.active_tasks.append(task)
            elif action.trigger.trigger_type == "event":
                task = asyncio.create_task(self._schedule_action(action))
                self.active_tasks.append(task)
            elif action.trigger.trigger_type == "page_load":
                await self._run_single_action(action)

    async def _schedule_action(self, action: ActionPayload):
        """Wait for action's trigger, then execute it."""
        if action.trigger and await self.wait_for_trigger(action.trigger):
            await self._run_single_action(action)

    async def _run_single_action(self, action: ActionPayload):
        """Run a single action."""
        async with self._action_lock:
            if action.action_type == "script":
                await self._run_script(action)

    async def wait_for_trigger(
        self,
        trigger: Trigger,
        poll_interval: float = 3.0,
    ) -> bool:
        """Wait for a trigger condition to be met.

        Args:
            trigger: Trigger specification
            poll_interval: Seconds between Matomo queries for event triggers

        Returns:
            True if trigger fired, False if timeout
        """
        if trigger.trigger_type == "time":
            if trigger.delay and trigger.delay > 0:
                await asyncio.sleep(trigger.delay)
            return True

        elif trigger.trigger_type == "page_load":
            return True

        elif trigger.trigger_type == "event":
            if not trigger.site or not trigger.event_match:
                print(f"Event trigger missing required fields: site={trigger.site}, event_match={trigger.event_match}")
                return False

            matomo = get_matomo_client()
            elapsed = 0.0
            timeout = trigger.timeout

            while elapsed < timeout:
                event = matomo.find_event(
                    site=trigger.site,
                    category=trigger.event_category,
                    name_contains=trigger.event_match,
                )

                if event:
                    print(f"Trigger matched: {event.category}/{event.name}")
                    return True

                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            print(f"Trigger timeout: no match for {trigger.event_category}/{trigger.event_match} on {trigger.site}")
            return False

        return False

    async def _run_script(self, action: ActionPayload):
        """
        Execute a Python script action.

        Args:
            action: Script action specification
        """
        script_path = action.script_path

        if not script_path:
            self.actions_log.append({
                "type": "script",
                "error": "No script_path specified",
                "success": False,
            })
            return

        # Resolve script path relative to universe directory
        if self.universe_path and not Path(script_path).is_absolute():
            script_path = str(self.universe_path / script_path)

        env = os.environ.copy()
        cmd = [sys.executable, script_path]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )

            if result.returncode == 0:
                self.actions_log.append({
                    "type": "script",
                    "script": script_path,
                    "success": True,
                    "output": result.stdout[:500] if result.stdout else None,
                })
                if result.stdout:
                    print(f"  {result.stdout.strip()}")
            else:
                self.actions_log.append({
                    "type": "script",
                    "script": script_path,
                    "error": result.stderr[:500] if result.stderr else "Unknown error",
                    "success": False,
                })
                print(f"  Script failed: {result.stderr[:200] if result.stderr else 'Unknown error'}")
        except subprocess.TimeoutExpired:
            self.actions_log.append({
                "type": "script",
                "script": script_path,
                "error": "Timeout (>60s)",
                "success": False,
            })
        except Exception as e:
            self.actions_log.append({
                "type": "script",
                "script": script_path,
                "error": str(e),
                "success": False,
            })

    async def cleanup(self):
        """Cancel all active trigger tasks."""
        for task in self.active_tasks:
            if not task.done():
                task.cancel()
        self.active_tasks.clear()
