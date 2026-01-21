"""Scene management for adversarial benchmark scenarios."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .helpers import get_zoo_cli_command
from .models import Scene, Trigger, InjectionPayload, load_scene

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
    """Manages adversarial scene activation and verification."""

    def __init__(self, zoo: Zoo):
        self.zoo = zoo
        self.active_tasks: list[asyncio.Task] = []
        self.start_time: float | None = None
        self.injections_log: list[dict] = []  # Track all injections for verification

    async def load_and_activate_scene(
        self, scene_name: str, task_start_time: float, scenes_dir: Path | None = None
    ) -> Scene:
        """
        Load a scene from file and activate it.

        Args:
            scene_name: Name of the scene file (without .yaml extension)
            task_start_time: Timestamp when the task started
            scenes_dir: Directory containing scene files (default: pet_to_wild/scenes)
        """
        # Default scenes directory
        if scenes_dir is None:
            scenes_dir = Path("pet_to_wild/scenes")

        scene_path = scenes_dir / f"{scene_name}.yaml"
        if not scene_path.exists():
            raise FileNotFoundError(f"Scene file not found: {scene_path}")

        scene = load_scene(scene_path)
        await self.activate_scene(scene, task_start_time)
        return scene

    async def activate_scene(self, scene: Scene, task_start_time: float):
        """
        Activate scene based on its triggers.

        Args:
            scene: Scene to activate
            task_start_time: Timestamp when the task started (for time-based triggers)
        """
        self.start_time = task_start_time

        for trigger in scene.triggers:
            if trigger.trigger_type == "time":
                # Schedule time-based injection
                task = asyncio.create_task(self._schedule_time_trigger(trigger, scene))
                self.active_tasks.append(task)
            elif trigger.trigger_type == "event":
                # TODO: Event-based triggers (future)
                pass
            elif trigger.trigger_type == "page_load":
                # Inject immediately (before agent navigates)
                await self._execute_injections(scene)

    async def _schedule_time_trigger(self, trigger: Trigger, scene: Scene):
        """Wait for delay, then execute injections."""
        if trigger.delay is None:
            return

        await asyncio.sleep(trigger.delay)
        await self._execute_injections(scene)

    async def _execute_injections(self, scene: Scene):
        """Execute all injections for a scene."""
        for injection in scene.injections:
            if injection.injection_type == "script":
                await self._inject_script(injection)

    async def _inject_script(self, injection: InjectionPayload):
        """
        Execute a Python script injection.

        Args:
            injection: Script injection specification
        """
        script_path = injection.script_path

        if not script_path:
            self.injections_log.append({
                "type": "script",
                "error": "No script_path specified",
                "success": False,
            })
            return

        # Build environment with ZOO_CLI_PATH if available
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
                self.injections_log.append({
                    "type": "script",
                    "script": script_path,
                    "success": True,
                    "output": result.stdout[:500] if result.stdout else None,  # Truncate long output
                })
            else:
                self.injections_log.append({
                    "type": "script",
                    "script": script_path,
                    "error": result.stderr[:500] if result.stderr else "Unknown error",
                    "success": False,
                })
        except subprocess.TimeoutExpired:
            self.injections_log.append({
                "type": "script",
                "script": script_path,
                "error": "Timeout (>60s)",
                "success": False,
            })
        except Exception as e:
            self.injections_log.append({
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
