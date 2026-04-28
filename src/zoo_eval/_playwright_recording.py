"""Playwright-native video recording helper, shared by browser_use and codex runners.

We launch chromium under Playwright (so we get its context-level video recording,
which renders properly in our headless aarch64 environment) and expose the CDP
WebSocket URL. Whatever MCP/agent connects over CDP and drives the existing page
gets captured for free.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


class PlaywrightRecording:
    """Holds Playwright objects backing a recorded run; close() finalizes the .webm."""

    def __init__(self, pw, pw_browser, pw_context, debug_port: int):
        self.pw = pw
        self.pw_browser = pw_browser
        self.pw_context = pw_context
        self.debug_port = debug_port

    async def close(self) -> None:
        for closer in (self.pw_context.close, self.pw_browser.close, self.pw.stop):
            try:
                await closer()
            except Exception as e:
                logger.debug(f"playwright recording close: {e}")


async def start_playwright_recording(
    video_subdir: Path,
    proxy_url: str,
    headless: bool,
    start_url: str | None = None,
) -> tuple[str, PlaywrightRecording]:
    """Launch chromium with a recorded BrowserContext.

    Returns (cdp_ws_url, PlaywrightRecording). Pass cdp_ws_url to anything that
    can attach over CDP (browser_use.Browser, playwright-mcp's --cdp-endpoint, ...)
    so it drives the same chromium the recording is on.

    If start_url is given, the page is navigated there before this function
    returns — so the resulting video starts on the target page rather than a
    blank canvas while the agent boots.
    """
    from playwright.async_api import async_playwright

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        debug_port = s.getsockname()[1]

    video_subdir.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    pw_browser = await pw.chromium.launch(
        headless=headless,
        args=[
            "--ignore-certificate-errors",
            "--no-sandbox",
            f"--remote-debugging-port={debug_port}",
        ],
        proxy={"server": proxy_url},
    )
    pw_context = await pw_browser.new_context(
        record_video_dir=str(video_subdir),
        record_video_size={"width": 1280, "height": 720},
        ignore_https_errors=True,
        viewport={"width": 1280, "height": 720},
    )
    pw_page = await pw_context.new_page()
    if start_url:
        try:
            await pw_page.goto(start_url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            logger.debug(f"pre-navigation to {start_url} failed: {e}")

    deadline = time.time() + 10
    last_err: Exception | None = None
    cdp_ws_url: str | None = None
    while time.time() < deadline:
        try:
            resp = json.loads(
                urllib.request.urlopen(
                    f"http://127.0.0.1:{debug_port}/json/version", timeout=2
                ).read()
            )
            cdp_ws_url = resp["webSocketDebuggerUrl"]
            break
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.2)

    if cdp_ws_url is None:
        await PlaywrightRecording(pw, pw_browser, pw_context, debug_port).close()
        raise RuntimeError(f"Could not fetch CDP URL on port {debug_port}: {last_err}")

    return cdp_ws_url, PlaywrightRecording(pw, pw_browser, pw_context, debug_port)
