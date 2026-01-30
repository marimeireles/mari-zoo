"""Scene management for benchmark scenarios."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from .models import Scene, Trigger, ActionPayload, AgentTrigger, load_scene

if TYPE_CHECKING:
    from .zoo import Zoo
    from .event_source import EventSource

logger = logging.getLogger(__name__)

# Type alias - browser_use uses its own Page wrapper, not Playwright
Page = object


class SceneManager:
    """Manages scene activation and verification.

    ## Generic API (works with any harness)

    Use these methods for harness-agnostic scene management:

        scene_manager = SceneManager(zoo, universe_path, event_source=my_event_source)
        await scene_manager.load_and_setup("scene_name")  # Runs setup scripts
        await scene_manager.setup_triggers()               # Sets up all triggers
        # ... run your agent ...
        await scene_manager.cleanup()

    ## browser_use-specific API (legacy)

    The attach_to_browser() method uses CDP and only works with browser_use:

        scene_manager = SceneManager(zoo, universe_path)  # No event_source
        await scene_manager.load_and_setup("scene_name")
        # Later, when browser is ready:
        await scene_manager.attach_to_browser(browser)    # browser_use only!
    """

    def __init__(
        self,
        zoo: "Zoo",
        universe_path: Path | None = None,
        universe_sites: list[str] | None = None,
        event_source: "EventSource | None" = None,
    ):
        """Initialize SceneManager.

        Args:
            zoo: Zoo instance for environment access
            universe_path: Path to the universe directory
            universe_sites: List of sites in the universe
            event_source: Optional EventSource for proxy-based triggers.
                         If None, falls back to CDP when browser is attached.
        """
        self.zoo = zoo
        self.universe_path = universe_path
        self.universe_sites = universe_sites or []
        self.event_source = event_source

        self.active_tasks: list[asyncio.Task] = []
        self.start_time: float | None = None
        self.actions_log: list[dict] = []  # Track all actions for verification
        self._action_lock = asyncio.Lock()  # Prevent concurrent action execution
        self._scene: Scene | None = None  # Current active scene
        self._browsers: list = []  # Browser instances for CDP triggers
        self._trigger_events: dict[str, asyncio.Event] = {}  # Track fired triggers by action id
        self._handler_ids: list[str] = []  # Track EventSource handler IDs for cleanup
        self._event_source_started = False

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

    async def load_and_setup(self, scene_name: str) -> Scene:
        """Load a scene and run setup scripts.

        This should be called BEFORE the browser is created.
        Call attach_to_browser() after browser is ready to enable triggers.

        Args:
            scene_name: Name of the scene file (without .yaml extension)
        """
        if self.universe_path is None:
            raise ValueError("universe_path must be set to load scenes")

        scenes_dir = self.universe_path / "scenes"
        scene_path = scenes_dir / f"{scene_name}.yaml"

        if not scene_path.exists():
            raise FileNotFoundError(f"Scene file not found: {scene_path}")

        scene = load_scene(scene_path)
        self._scene = scene

        # Run setup actions (before browser starts)
        await self._run_actions(scene.setup, "setup script")

        return scene

    async def start_event_source(self) -> None:
        """Start the event source if configured.

        Call this before setting up triggers. Can be called multiple times safely.
        """
        if self.event_source and not self._event_source_started:
            await self.event_source.start()
            self._event_source_started = True
            logger.info("EventSource started for SceneManager")

    async def setup_triggers(self) -> None:
        """Set up all triggers for the current scene.

        This is the preferred method when using proxy-based event source.
        For CDP-based triggers, use attach_to_browser() instead.
        """
        if self._scene is None:
            return

        # Start event source if needed
        await self.start_event_source()

        for action in self._scene.actions:
            action_id = f"{action.script_path}_{id(action)}"

            if action.trigger is None:
                await self._run_single_action(action)
            elif action.trigger.trigger_type == "request":
                await self._setup_request_trigger(action, action_id)
            elif action.trigger.trigger_type == "poll":
                task = asyncio.create_task(self._setup_poll_trigger(action, action_id))
                self.active_tasks.append(task)
            elif action.trigger.trigger_type == "time":
                if action.trigger.delay == 0:
                    await self._run_single_action(action)
                else:
                    task = asyncio.create_task(self._schedule_time_action(action))
                    self.active_tasks.append(task)
            elif action.trigger.trigger_type == "page_load":
                await self._run_single_action(action)

    async def _setup_request_trigger(self, action: ActionPayload, action_id: str) -> None:
        """Set up a request trigger using EventSource (proxy) or CDP (fallback)."""
        if not action.trigger:
            return

        trigger = action.trigger

        # Build the URL pattern
        if trigger.url_pattern:
            pattern = trigger.url_pattern
        elif trigger.url_contains:
            # Convert simple contains to regex pattern
            pattern = re.escape(trigger.url_contains)
        else:
            logger.warning(f"Request trigger missing url_pattern or url_contains")
            return

        # Create or get shared event for this action
        if action_id not in self._trigger_events:
            self._trigger_events[action_id] = asyncio.Event()
        fired_event = self._trigger_events[action_id]

        # Define the handler
        async def on_request_match(event):
            if fired_event.is_set():
                return  # Already fired

            # Check method if specified
            if trigger.method and event.method.upper() != trigger.method.upper():
                return

            logger.info(f"Request trigger matched: {event.url}")
            fired_event.set()
            await self._run_single_action(action)

        # Use EventSource if available, otherwise we'll need CDP via attach_to_browser
        if self.event_source:
            handler_id = self.event_source.on_request(
                pattern,
                on_request_match,
                wait_for_response=trigger.wait_for_load,
            )
            self._handler_ids.append(handler_id)
            logger.debug(f"Registered proxy-based request trigger for pattern: {pattern}")

            # Set up timeout task
            async def timeout_watcher():
                try:
                    await asyncio.wait_for(fired_event.wait(), timeout=trigger.timeout)
                except asyncio.TimeoutError:
                    logger.debug(f"Request trigger timed out for pattern: {pattern}")

            task = asyncio.create_task(timeout_watcher())
            self.active_tasks.append(task)
        else:
            # No event source - will need to use CDP when browser is attached
            logger.debug(f"No EventSource, request trigger will use CDP: {pattern}")


    async def _setup_poll_trigger(self, action: ActionPayload, action_id: str):
        """Poll an endpoint until condition is met."""
        if not action.trigger:
            return

        trigger = action.trigger
        if not trigger.poll_endpoint:
            print(f"Poll trigger missing poll_endpoint")
            return

        # Track this trigger
        if action_id not in self._trigger_events:
            self._trigger_events[action_id] = asyncio.Event()
        fired_event = self._trigger_events[action_id]

        elapsed = 0.0
        proxy_url = os.environ.get("ZOO_PROXY_URL", "http://localhost:3128")

        async with httpx.AsyncClient(proxy=proxy_url, verify=False) as client:
            while elapsed < trigger.timeout and not fired_event.is_set():
                try:
                    response = await client.get(trigger.poll_endpoint, timeout=10)
                    text = response.text

                    # Check if condition is met
                    if trigger.poll_contains:
                        if trigger.poll_contains.lower() in text.lower():
                            print(f"Poll trigger matched: found '{trigger.poll_contains}' at {trigger.poll_endpoint}")
                            fired_event.set()
                            await self._run_single_action(action)
                            return
                    else:
                        # No condition = just check for 200 OK
                        if response.status_code == 200:
                            print(f"Poll trigger matched: 200 OK from {trigger.poll_endpoint}")
                            fired_event.set()
                            await self._run_single_action(action)
                            return

                except Exception as e:
                    logger.debug(f"Poll attempt failed: {e}")  # Keep polling

                await asyncio.sleep(trigger.poll_interval)
                elapsed += trigger.poll_interval

        if not fired_event.is_set():
            print(f"Poll trigger timed out waiting for: {trigger.poll_endpoint}")

    async def _schedule_time_action(self, action: ActionPayload):
        """Schedule an action after a time delay."""
        if action.trigger and action.trigger.delay:
            await asyncio.sleep(action.trigger.delay)
        await self._run_single_action(action)

    # Legacy method for backwards compatibility
    async def load_and_activate_scene(
        self, scene_name: str, task_start_time: float
    ) -> Scene:
        """
        Load a scene from file and activate it.

        DEPRECATED: Use load_and_setup() + attach_to_page() instead.
        This method only supports time/page_load triggers, not request triggers.

        Args:
            scene_name: Name of the scene file (without .yaml extension)
            task_start_time: Timestamp when the task started
        """
        self.start_time = task_start_time

        # Load and run setup
        scene = await self.load_and_setup(scene_name)

        # For backwards compat, activate non-request triggers immediately
        for action in scene.actions:
            if action.trigger is None:
                await self._run_single_action(action)
            elif action.trigger.trigger_type == "time":
                if action.trigger.delay == 0:
                    await self._run_single_action(action)
                else:
                    task = asyncio.create_task(self._schedule_time_action(action))
                    self.active_tasks.append(task)
            elif action.trigger.trigger_type == "page_load":
                await self._run_single_action(action)
            elif action.trigger.trigger_type == "request":
                print(f"Warning: request trigger requires attach_to_page() - skipping action")

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

    async def _run_single_action(self, action: ActionPayload):
        """Run a single action."""
        async with self._action_lock:
            if action.action_type == "script":
                await self._run_script(action)

    async def wait_for_trigger(
        self,
        trigger: Trigger,
    ) -> bool:
        """Wait for a trigger condition to be met.

        Args:
            trigger: Trigger specification

        Returns:
            True if trigger fired, False if timeout
        """
        if trigger.trigger_type == "time":
            if trigger.delay and trigger.delay > 0:
                await asyncio.sleep(trigger.delay)
            return True

        elif trigger.trigger_type == "page_load":
            return True

        elif trigger.trigger_type == "request":
            # Request triggers are handled via EventSource or CDP listeners
            # This method is mainly for agent start triggers
            logger.warning("Request triggers should use setup_triggers() or attach_to_browser()")
            return True

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
        """Cancel all active trigger tasks and clean up resources."""
        # Cancel active tasks
        for task in self.active_tasks:
            if not task.done():
                task.cancel()
        self.active_tasks.clear()
        self._trigger_events.clear()
        self._browsers.clear()

        # Clean up EventSource handlers
        if self.event_source:
            for handler_id in self._handler_ids:
                self.event_source.remove_handler(handler_id)
            self._handler_ids.clear()

            # Stop EventSource if we started it
            if self._event_source_started:
                await self.event_source.stop()
                self._event_source_started = False
