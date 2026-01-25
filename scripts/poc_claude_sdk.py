#!/usr/bin/env python3
"""Proof of concept for Claude Agent SDK + playwright-mcp integration.

Run with:
    python scripts/poc_claude_sdk.py

Requires:
    - ANTHROPIC_API_KEY environment variable
    - npx available (for playwright-mcp)
"""

import asyncio
import os
import sys

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)


async def main():
    """Test Claude Agent SDK with playwright-mcp."""

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable required")
        sys.exit(1)

    print("=== Claude Agent SDK + Playwright MCP POC ===\n")

    # Configure playwright-mcp as stdio server
    options = ClaudeAgentOptions(
        mcp_servers={
            "playwright": {
                "command": "npx",
                "args": ["@playwright/mcp@latest", "--browser", "firefox"],
            }
        },
        # Allow all playwright tools
        allowed_tools=["mcp__playwright__*"],
        # Model selection
        model="sonnet",
        # Max turns to prevent infinite loops
        max_turns=20,
    )

    print("Options configured:")
    print(f"  - MCP servers: playwright (firefox)")
    print(f"  - Model: sonnet")
    print(f"  - Max turns: 20")
    print()

    # Run the agent - SDK handles the agentic loop automatically
    steps = 0
    prompt = "Navigate to https://example.com and tell me the page title"

    print(f"Prompt: {prompt}\n")
    print("--- Agent execution ---\n")

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        # Truncate long text
                        text = block.text[:200] + "..." if len(block.text) > 200 else block.text
                        print(f"[Text] {text}")
                    elif isinstance(block, ToolUseBlock):
                        steps += 1
                        print(f"[Tool #{steps}] {block.name}")
                        if hasattr(block, "input") and block.input:
                            # Show key inputs
                            for k, v in list(block.input.items())[:2]:
                                v_str = str(v)[:50] + "..." if len(str(v)) > 50 else str(v)
                                print(f"         {k}: {v_str}")

            elif isinstance(message, ResultMessage):
                print(f"\n--- Complete ---")
                print(f"Success: {not message.is_error}")
                print(f"Turns: {message.num_turns}")
                print(f"Duration: {message.duration_ms}ms")
                print(f"Cost: ${message.total_cost_usd:.4f}" if message.total_cost_usd else "Cost: N/A")
                print(f"Result: {message.result[:200] if message.result else 'None'}...")
                break

    except Exception as e:
        print(f"\nError: {type(e).__name__}: {e}")
        sys.exit(1)

    print(f"\nTotal tool calls: {steps}")


if __name__ == "__main__":
    asyncio.run(main())
