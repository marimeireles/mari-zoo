"""OpenAI Codex CLI runner with playwright-mcp.

Drives `codex exec` as a subprocess for each agent run. Codex uses MCP servers
for browser tooling — the `zoo-playwright` server (registered globally via
`codex mcp add`) provides chromium-driving tools that mirror the ones used by
the claude_sdk runner.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from ._playwright_recording import start_playwright_recording
from .base_agent_runner import BaseAgentRunner
from .models import AgentResult, RunConfig, Task, TaskAgentConfig, TaskResult, Universe
from .scenes import SceneManager
from .zoo import Zoo


# Tool names emitted by playwright-mcp via Codex's JSONL events; tracked for step
# count + URL bookkeeping. These mirror the ones the claude_sdk runner watches.
_NAVIGATE_TOOLS = ("zoo-playwright/browser_navigate", "browser_navigate")


class CodexRunner(BaseAgentRunner):
    """Runs tasks by spawning the Codex CLI in non-interactive `exec` mode."""

    def __init__(
        self,
        zoo: Zoo,
        config: RunConfig | None = None,
        universe_path: Path | None = None,
        universe: Universe | None = None,
    ):
        super().__init__(zoo, config, universe_path, universe)

    async def setup(self) -> None:
        """Verify codex is installed and a zoo-playwright MCP server is registered.

        We don't auto-register the MCP here — it's a one-time global setup
        (see notes in this runner's docstring). Bail loudly if missing.
        """
        proc = await asyncio.create_subprocess_exec(
            "codex", "mcp", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"codex CLI not available: {err.decode(errors='ignore')}")
        if b"zoo-playwright" not in out:
            raise RuntimeError(
                "codex MCP server 'zoo-playwright' is not registered. Run:\n"
                "  codex mcp add zoo-playwright -- npx @playwright/mcp@latest "
                "--browser chromium --proxy-server <ZOO_PROXY_URL> "
                "--ignore-https-errors --headless"
            )

    async def teardown(self) -> None:
        pass

    def _video_dir_for(
        self, task: Task, autonomy_level: str, agent_name: str | None
    ) -> Path | None:
        """Return per-(task, level, agent) video output dir, or None if disabled.

        Mirrors BrowserUseRunner._video_dir_for so videos from both harnesses
        live under the same logs/<run>/videos/<universe>/<leaf>/ layout.
        """
        if not self.config.record_videos or self.config.video_dir is None:
            return None
        universe = self.universe.name if self.universe else "unknown"
        leaf = f"task{task.task_id}_{autonomy_level}"
        if agent_name:
            leaf = f"{leaf}_{agent_name}"
        return Path(self.config.video_dir) / universe / leaf

    def _get_agent_role(self, agent_config: TaskAgentConfig) -> str:
        universe_agent = self._get_universe_agent(agent_config.name)
        return universe_agent.role if universe_agent else ""

    async def _run_single_agent(
        self,
        agent_config: TaskAgentConfig,
        task: Task,
        start_url: str,
        autonomy_level: str = "L1",
        scene_manager: SceneManager | None = None,
    ) -> AgentResult:
        start_time = time.time()
        steps = 0
        final_url: str | None = None
        events: list[dict[str, Any]] = []
        recording = None

        try:
            agent_context = self._build_agent_context(agent_config, task)
            task_prompt = self._build_full_task(agent_config, task, start_url, autonomy_level)
            prompt = (
                f"{agent_context}\n\n{task_prompt}\n\n"
                "Use the zoo-playwright MCP tools (browser_navigate, browser_click, "
                "browser_snapshot, etc.) to complete this task. When done, give your "
                "final answer as plain text."
            )

            model = self._resolve_model(agent_config)

            # If video recording is enabled, pre-launch chromium under Playwright
            # (with native context-level recording + pre-navigation to start_url)
            # and point playwright-mcp at it via --cdp-endpoint. Codex then uses
            # the same chromium that's being recorded.
            cdp_endpoint: str | None = None
            video_subdir = self._video_dir_for(task, autonomy_level, agent_config.name)
            if self.config.record_videos and video_subdir is not None:
                cdp_endpoint, recording = await start_playwright_recording(
                    video_subdir=video_subdir,
                    proxy_url=self.zoo.config.proxy_url,
                    headless=self.config.headless,
                    start_url=start_url,
                )

            with tempfile.NamedTemporaryFile(
                mode="w+", suffix=".txt", delete=False, prefix="codex_last_"
            ) as last_msg_file:
                last_msg_path = last_msg_file.name

            try:
                cmd = [
                    "codex", "exec",
                    "--json",
                    "--skip-git-repo-check",
                    "--ephemeral",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "-m", model,
                    "-o", last_msg_path,
                ]
                if cdp_endpoint is not None:
                    # Override the global zoo-playwright MCP server's args so this
                    # codex run attaches to our recorded chromium instead of
                    # spawning its own. TOML array syntax for the -c override.
                    mcp_args = [
                        "@playwright/mcp@latest",
                        "--cdp-endpoint", cdp_endpoint,
                    ]
                    cmd.extend([
                        "-c", f"mcp_servers.zoo-playwright.command=\"npx\"",
                        "-c", "mcp_servers.zoo-playwright.args=" + json.dumps(mcp_args),
                    ])
                cmd.append("-")  # read prompt from stdin

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={**os.environ},
                    # New session so the codex node wrapper + its codex_aarch64
                    # child + any playwright-mcp grandchildren share a process
                    # group we can SIGKILL atomically on timeout. Without this,
                    # proc.kill() only kills the wrapper and the codex binary
                    # orphans (PPID=1) and holds the CDP session, deadlocking
                    # recording.close() for ~100s.
                    start_new_session=True,
                )

                async def _drain_stdout() -> None:
                    nonlocal steps, final_url
                    assert proc.stdout is not None
                    while True:
                        line = await proc.stdout.readline()
                        if not line:
                            return
                        try:
                            evt = json.loads(line.decode(errors="ignore"))
                        except json.JSONDecodeError:
                            continue
                        events.append(evt)
                        # Track tool calls (Codex uses 'mcp_tool_call' events; shape varies by version).
                        et = evt.get("type") or evt.get("event")
                        if et and "tool" in et:
                            steps += 1
                            tool_name = (
                                evt.get("name")
                                or evt.get("tool")
                                or (evt.get("payload") or {}).get("name")
                            )
                            if tool_name and any(t in tool_name for t in _NAVIGATE_TOOLS):
                                args = evt.get("arguments") or evt.get("input") or {}
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except Exception:
                                        args = {}
                                url = args.get("url") if isinstance(args, dict) else None
                                if url:
                                    final_url = url

                drain_task = asyncio.create_task(_drain_stdout())
                try:
                    proc.stdin.write(prompt.encode())  # type: ignore[union-attr]
                    await proc.stdin.drain()  # type: ignore[union-attr]
                    proc.stdin.close()  # type: ignore[union-attr]
                except Exception:
                    pass

                try:
                    await asyncio.wait_for(
                        proc.wait(), timeout=self.config.timeout_seconds
                    )
                except asyncio.TimeoutError:
                    # Kill the whole process group to take down codex_aarch64
                    # + any playwright-mcp children, not just the wrapper.
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        pass
                    drain_task.cancel()
                    return AgentResult(
                        agent_name=agent_config.name,
                        agent_role=self._get_agent_role(agent_config),
                        success=False,
                        error=f"Timeout after {self.config.timeout_seconds}s",
                        steps=steps,
                        duration_seconds=time.time() - start_time,
                    )

                await drain_task

                final_answer: str | None = None
                try:
                    with open(last_msg_path, "r") as f:
                        final_answer = f.read().strip() or None
                except Exception:
                    pass

                stderr_bytes = b""
                try:
                    if proc.stderr is not None:
                        stderr_bytes = await proc.stderr.read()
                except Exception:
                    pass

                return AgentResult(
                    agent_name=agent_config.name,
                    agent_role=self._get_agent_role(agent_config),
                    success=proc.returncode == 0 and final_answer is not None,
                    answer=final_answer,
                    final_url=final_url,
                    page_content=None,
                    error=(stderr_bytes.decode(errors="ignore")[:500]
                           if proc.returncode != 0 else None),
                    steps=steps,
                    duration_seconds=time.time() - start_time,
                    raw_result={"events": events, "returncode": proc.returncode},
                )
            finally:
                try:
                    os.unlink(last_msg_path)
                except Exception:
                    pass

        except Exception as e:
            return AgentResult(
                agent_name=agent_config.name,
                agent_role=self._get_agent_role(agent_config),
                success=False,
                error=str(e),
                steps=steps,
                duration_seconds=time.time() - start_time,
            )
        finally:
            if recording is not None:
                await recording.close()

    async def run_tasks(self, tasks: list[Task]) -> list[TaskResult]:
        services = []
        if self.universe:
            all_sites = set()
            for task in tasks:
                all_sites.update(task.sites)
            services = self.universe.get_services_for_sites(list(all_sites))

        # Drop services that aren't actually running in this compose stack.
        running = self.zoo._running_services()
        if running:
            services = [s for s in services if s in running]

        # Skip the heavy zoo.restart() if all required services are already
        # healthy. Restarting postgres each task wipes the golden templates
        # (postgres restores data-golden.tar on every restart), which forces
        # reset_sites_fast to recreate them — and that races with gitea-zoo
        # auto-reconnecting to gitea_db, hanging the benchmark for ~2min/task.
        # The per-task reset_sites_fast already handles state hygiene; we only
        # need a heavy restart if something is genuinely broken.
        if services and self.zoo.wait_for_services(services, timeout=10, verbose=False):
            pass  # all healthy, no restart needed
        else:
            self.zoo.restart(services if services else None)
            if services:
                self.zoo.wait_for_services(services, timeout=120, verbose=True)

        all_results: list[TaskResult] = []
        for task in tasks:
            if not task.agents:
                continue

            # Skip tasks whose required sites aren't backed by a running service
            # in this compose stack — running them would just produce garbage
            # answers from broken pages.
            if task.sites:
                missing = [s for s in task.sites if not self.zoo.is_site_available(s)]
                if missing:
                    print(f"  Skipping task {task.task_id}: site(s) unavailable: {', '.join(missing)}")
                    continue

            start_url = self.zoo.resolve_url(task.start_url)
            agents = list(task.agents.values())

            levels_to_run = []
            for autonomy_level in self.config.autonomy_levels:
                if (task.task_id, autonomy_level) in self.config.completed_pairs:
                    continue
                has_level = any(
                    autonomy_level in agent_config.autonomy_levels for agent_config in agents
                )
                if has_level:
                    levels_to_run.append(autonomy_level)

            for autonomy_level in levels_to_run:
                if (task.require_reset or task.scene_name) and self.universe:
                    sites_to_reset = task.sites if task.sites else self.universe.sites
                    self.zoo.reset_sites_fast(sites_to_reset)

                task_start_time = time.time()

                # Set up scene (runs setup scripts that seed the gitea repos,
                # deliver mail to the agent, etc.). Without this, agents log
                # in to an empty inbox / missing repos. Mirrors the pattern in
                # claude_sdk_runner.run_tasks.
                scene_manager = None
                if task.scene_name and self.universe_path:
                    from .models import load_scene

                    scenes_dir = self.universe_path / "scenes"
                    scene_path = scenes_dir / f"{task.scene_name}.yaml"
                    scene = load_scene(scene_path) if scene_path.exists() else None

                    use_proxy = self.config.use_proxy_events or (scene and scene.needs_proxy_events)
                    event_source = None
                    if use_proxy:
                        from .proxy_event_source import ProxyEventSource
                        event_source = ProxyEventSource(
                            redis_url=self.config.redis_url,
                            session_id=str(uuid.uuid4()),
                        )

                    universe_sites = self.universe.sites if self.universe else []
                    scene_manager = SceneManager(
                        self.zoo,
                        self.universe_path,
                        universe_sites,
                        event_source=event_source,
                    )
                    try:
                        await scene_manager.load_and_setup(task.scene_name)
                        scene_manager.start_time = task_start_time
                        await scene_manager.setup_triggers()
                    except Exception as e:
                        print(f"  Scene setup failed for task {task.task_id}: {e}")

                try:
                    agent_results = await asyncio.gather(*[
                        self._run_single_agent(a, task, start_url, autonomy_level, scene_manager) for a in agents
                    ])
                finally:
                    if scene_manager:
                        try:
                            await scene_manager.cleanup()
                        except Exception:
                            pass

                combined_answer = "\n\n".join(
                    f"[{r.agent_name}]: {r.answer}" for r in agent_results if r.answer
                )
                total_steps = sum(r.steps for r in agent_results)
                last = agent_results[-1] if agent_results else None
                all_results.append(TaskResult(
                    task_id=task.task_id,
                    agent_results=agent_results,
                    agent_answer=combined_answer or None,
                    final_url=last.final_url if last else None,
                    page_content=None,
                    steps=total_steps,
                    duration_seconds=time.time() - task_start_time,
                    raw_result=last.raw_result if last else None,
                    autonomy_level=autonomy_level,
                    scene_name=task.scene_name,
                ))

        return all_results
