"""Scene management for benchmark scenarios."""

from __future__ import annotations

import asyncio
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

# Type alias - browser_use uses its own Page wrapper, not Playwright
Page = object


class SceneManager:
    """Manages scene activation and verification.

    Supports CDP-based request triggers that fire when the browser
    makes requests matching specified URL patterns.
    """

    def __init__(self, zoo: Zoo, universe_path: Path | None = None, universe_sites: list[str] | None = None):
        self.zoo = zoo
        self.universe_path = universe_path
        self.universe_sites = universe_sites or []
        self.active_tasks: list[asyncio.Task] = []
        self.start_time: float | None = None
        self.actions_log: list[dict] = []  # Track all actions for verification
        self._action_lock = asyncio.Lock()  # Prevent concurrent action execution
        self._scene: Scene | None = None  # Current active scene
        self._browsers: list = []  # Browser instances for CDP triggers
        self._trigger_events: dict[str, asyncio.Event] = {}  # Track fired triggers by action id

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

    async def attach_to_browser(self, browser):
        """Attach to a browser to enable CDP-based triggers.

        Can be called multiple times for multi-agent scenarios.
        Each browser will have listeners attached for request triggers.

        Args:
            browser: browser_use Browser instance
        """
        self._browsers.append(browser)

        if self._scene is None:
            return

        # First browser attachment: set up non-browser-specific triggers
        is_first_browser = len(self._browsers) == 1

        for action in self._scene.actions:
            action_id = f"{action.script_path}_{id(action)}"

            if action.trigger is None:
                if is_first_browser:
                    await self._run_single_action(action)
            elif action.trigger.trigger_type == "request":
                await self._setup_request_trigger_cdp(action, browser, action_id)
            elif action.trigger.trigger_type == "poll":
                if is_first_browser:
                    task = asyncio.create_task(self._setup_poll_trigger(action, action_id))
                    self.active_tasks.append(task)
            elif action.trigger.trigger_type == "time":
                if is_first_browser:
                    if action.trigger.delay == 0:
                        await self._run_single_action(action)
                    else:
                        task = asyncio.create_task(self._schedule_time_action(action))
                        self.active_tasks.append(task)
            elif action.trigger.trigger_type == "page_load":
                if is_first_browser:
                    await self._run_single_action(action)

    async def _setup_request_trigger_cdp(self, action: ActionPayload, browser, action_id: str):
        """Set up a CDP Network event listener for HTTP requests."""
        if not action.trigger:
            return

        trigger = action.trigger
        url_pattern = trigger.url_contains or trigger.url_pattern
        if not url_pattern:
            return

        # Create or get shared event for this action (across all browsers)
        if action_id not in self._trigger_events:
            self._trigger_events[action_id] = asyncio.Event()
        fired_event = self._trigger_events[action_id]

        # Track state for wait_for_load
        url_matched = {"value": False}
        load_event = asyncio.Event()

        def on_network_request(params, session_id):
            """Handle Network.requestWillBeSent CDP events."""
            request_info = params.get("request", {})
            url = request_info.get("url", "")
            method = request_info.get("method", "GET")

            if fired_event.is_set():
                return  # Already fired

            # Check method if specified
            if trigger.method and method.upper() != trigger.method.upper():
                return

            # Check URL pattern
            matches = False
            if trigger.url_contains and trigger.url_contains.lower() in url.lower():
                matches = True
            elif trigger.url_pattern and re.search(trigger.url_pattern, url):
                matches = True

            if matches:
                if trigger.wait_for_load:
                    # Mark URL as matched, wait for page load
                    url_matched["value"] = True
                else:
                    # Fire immediately
                    fired_event.set()
                    asyncio.create_task(self._run_single_action(action))

        def on_page_load(params, session_id):
            """Handle Page.loadEventFired CDP events."""
            if url_matched["value"] and not fired_event.is_set():
                fired_event.set()
                asyncio.create_task(self._run_single_action(action))

        try:
            cdp_session = await browser.get_or_create_cdp_session()
            await cdp_session.cdp_client.send_raw("Network.enable", session_id=cdp_session.session_id)
            cdp_session.cdp_client._event_registry.register("Network.requestWillBeSent", on_network_request)

            # If wait_for_load, also listen for page load event
            if trigger.wait_for_load:
                await cdp_session.cdp_client.send_raw("Page.enable", session_id=cdp_session.session_id)
                cdp_session.cdp_client._event_registry.register("Page.loadEventFired", on_page_load)
        except Exception:
            return

        # Set up timeout task
        async def timeout_watcher():
            try:
                await asyncio.wait_for(fired_event.wait(), timeout=trigger.timeout)
            except asyncio.TimeoutError:
                pass

        task = asyncio.create_task(timeout_watcher())
        self.active_tasks.append(task)

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
                            print(f"🎯 Poll trigger matched: found '{trigger.poll_contains}' at {trigger.poll_endpoint}")
                            fired_event.set()
                            await self._run_single_action(action)
                            return
                    else:
                        # No condition = just check for 200 OK
                        if response.status_code == 200:
                            print(f"🎯 Poll trigger matched: 200 OK from {trigger.poll_endpoint}")
                            fired_event.set()
                            await self._run_single_action(action)
                            return

                except Exception as e:
                    pass  # Keep polling

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
            # Request triggers are handled via CDP listeners
            # This method is mainly for agent start triggers
            print(f"Warning: request triggers should use attach_to_page()")
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
        """Cancel all active trigger tasks."""
        for task in self.active_tasks:
            if not task.done():
                task.cancel()
        self.active_tasks.clear()
        self._trigger_events.clear()
        self._browsers.clear()
