"""Data models for tasks and evaluations."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

# Shared constants for autonomy levels, environments, and complexities
AUTONOMY_LEVELS = ["L0", "L1", "L2"]
ENVIRONMENTS = ["domesticated", "tame", "wild"]
COMPLEXITIES = ["atomic", "compositional", "open_ended"]


class AgentHarness(str, Enum):
    """Agent execution harness."""

    BROWSER_USE = "browser_use"
    CLAUDE_SDK = "claude_sdk"


@dataclass
class RunConfig:
    """Configuration for task runs."""

    max_steps: int = 30
    timeout_seconds: float = 120.0  # 2 minutes default
    headless: bool = True
    save_traces: bool = True
    trace_dir: str = "./traces"
    model: str = "google/gemini-2.5-flash-lite"  # Model for agent (auto-detects provider)
    judge_model: str = "gpt-5.1"  # Model for LLM judge evaluation (auto-detects provider)
    shared_browser: bool = False  # If True, all agents share the same browser and memory
    autonomy_levels: list[str] = field(default_factory=lambda: list(AUTONOMY_LEVELS))  # Which levels to run
    completed_pairs: set[tuple[int, str]] = field(default_factory=set)  # (task_id, level) pairs to skip (for resume)
    harness: AgentHarness = AgentHarness.BROWSER_USE  # Which agent harness to use
    claude_model: str = "sonnet"  # Claude model for Claude SDK harness ("opus", "sonnet", "haiku")
    skip_zoo_reset: bool = False  # If True, skip Docker restart/reset (assume services are ready)
    # Proxy-based event source configuration (harness-agnostic scene triggers)
    use_proxy_events: bool = False  # Use Redis pub/sub for scene triggers (required for request triggers)
    redis_url: str = "redis://localhost:6379"  # Redis URL for proxy event source


class EvalType(str, Enum):
    STRING_MATCH = "string_match"
    URL_MATCH = "url_match"
    PROGRAM_HTML = "program_html"
    DB_MATCH = "db_match"
    LLM_JUDGE = "llm_judge"
    HUMAN_CRITIC = "human_critic"
    CUSTOM_FUNCTION = "custom_function"  # User-defined Python function for custom evaluation logic


@dataclass
class Subtask:
    """A subtask within a compositional task for granular scoring.

    Subtasks allow breaking down complex tasks into verifiable checkpoints.
    Each subtask has a binary pass/fail, and the task score is computed as:
    score = sum(passed_subtask_weights) / sum(all_weights)
    """

    id: str  # Unique identifier (e.g., "login", "create_fix")
    description: str  # What this subtask verifies
    weight: int = 1  # Importance weight (default: 1)
    eval_type: EvalType = EvalType.LLM_JUDGE  # How to evaluate this subtask

    @classmethod
    def from_dict(cls, data: dict) -> Subtask:
        eval_type = EvalType.LLM_JUDGE
        if data.get("eval_type"):
            try:
                eval_type = EvalType(data["eval_type"])
            except ValueError:
                pass  # Default to LLM_JUDGE
        return cls(
            id=data.get("id", ""),
            description=data.get("description", ""),
            weight=data.get("weight", 1),
            eval_type=eval_type,
        )


@dataclass
class SubtaskResult:
    """Result of evaluating a single subtask."""

    subtask_id: str
    description: str
    weight: int
    passed: bool  # Binary pass/fail
    evidence: str = ""  # Explanation from evaluator
    eval_type: EvalType = EvalType.LLM_JUDGE


class TaskComplexity(str, Enum):
    """Task complexity levels."""

    ATOMIC = "atomic"
    COMPOSITIONAL = "compositional"
    OPEN_ENDED = "open_ended"


class Environment(str, Enum):
    """Environment adversarial conditions."""

    DOMESTICATED = "domesticated"
    TAME = "tame"
    WILD = "wild"


@dataclass
class ReferenceAnswers:
    """Expected answers for string matching."""

    exact_match: str | None = None
    must_include: list[str] = field(default_factory=list)  # ALL must be present
    must_include_any: list[str] = field(default_factory=list)  # ANY ONE must be present

    @classmethod
    def from_dict(cls, data: dict | None) -> ReferenceAnswers | None:
        if not data:
            return None
        return cls(
            exact_match=data.get("exact_match"),
            must_include=data.get("must_include", []),
            must_include_any=data.get("must_include_any", []),
        )


@dataclass
class HTMLCheck:
    """Program HTML evaluation check."""

    url: str  # 'last' means final URL
    locator: str  # CSS selector or empty
    required_contents: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> HTMLCheck:
        return cls(
            url=data.get("url", "last"),
            locator=data.get("locator", ""),
            required_contents=data.get("required_contents", {}),
        )


@dataclass
class DBQuery:
    """Database query for dynamic evaluation."""

    database: str
    query: str
    db_type: str = "mysql"  # mysql or postgres
    match_type: str = "must_include"  # must_include, exact_match, or count

    @classmethod
    def from_dict(cls, data: dict | None) -> DBQuery | None:
        if not data:
            return None
        return cls(
            database=data.get("database", ""),
            query=data.get("query", ""),
            db_type=data.get("type", "mysql"),
            match_type=data.get("match_type", "must_include"),
        )


@dataclass
class Trigger:
    """Trigger specification for when a scene activates.

    Trigger types:
    - time: Activate after a delay (seconds)
    - request: Activate when agent makes HTTP request matching pattern (via proxy events)
    - poll: Activate when a condition is met (checked periodically)
    - page_load: Activate immediately before agent starts

    Request trigger fields (for type="request"):
    - url_contains: Substring to match in request URL (case-insensitive)
    - url_pattern: Regex pattern to match request URL
    - method: HTTP method to match (GET, POST, etc.) - optional
    - wait_for_load: Wait for page load event after URL match (default: True)

    Poll trigger fields (for type="poll"):
    - poll_endpoint: URL to check periodically
    - poll_contains: Text that must appear in response for trigger to fire
    - poll_interval: Seconds between checks (default: 3)

    Common fields:
    - timeout: Max seconds to wait for trigger (default: 600)
    """

    trigger_type: str  # "time" | "request" | "poll" | "page_load"
    delay: int | None = None  # For time triggers: seconds after task starts
    # Request trigger fields
    url_contains: str | None = None  # Substring to match in URL
    url_pattern: str | None = None  # Regex pattern to match URL
    method: str | None = None  # HTTP method to match (GET, POST, etc.)
    wait_for_load: bool = True  # Wait for page load after URL match (default: True)
    # Poll trigger fields
    poll_endpoint: str | None = None  # URL to check
    poll_contains: str | None = None  # Text to look for in response
    poll_interval: float = 3.0  # Seconds between polls
    # Common
    timeout: float = 600.0  # Max seconds to wait (default: 10 minutes)

    @classmethod
    def from_dict(cls, data: dict) -> Trigger:
        return cls(
            trigger_type=data.get("type", "time"),
            delay=data.get("delay"),
            url_contains=data.get("url_contains"),
            url_pattern=data.get("url_pattern"),
            method=data.get("method"),
            wait_for_load=data.get("wait_for_load", True),
            poll_endpoint=data.get("poll_endpoint"),
            poll_contains=data.get("poll_contains"),
            poll_interval=data.get("poll_interval", 3.0),
            timeout=data.get("timeout", 600.0),
        )


@dataclass
class ActionPayload:
    """Action that runs as part of a scene. See docs/authoring-scenes.md for action types."""

    action_type: str  # "script", "email", "gitea.repo", etc.
    data: dict = field(default_factory=dict)  # Action-specific fields
    description: str = ""
    trigger: Trigger | None = None
    script_path: str = ""  # Legacy: for script actions

    @classmethod
    def from_dict(cls, data: dict) -> ActionPayload:
        trigger = None
        if data.get("trigger"):
            trigger = Trigger.from_dict(data["trigger"])

        action_type = data.get("type", "script")
        known_fields = {"type", "trigger", "script_path"}
        action_data = {k: v for k, v in data.items() if k not in known_fields}

        return cls(
            action_type=action_type,
            data=action_data,
            description=data.get("description", ""),
            trigger=trigger,
            script_path=data.get("script_path", ""),
        )


@dataclass
class AgentTrigger:
    """Defines when an agent should be spawned during a scene."""

    name: str  # Agent name (must match agent defined in task)
    trigger: Trigger  # When to spawn this agent

    @classmethod
    def from_dict(cls, data: dict) -> AgentTrigger:
        return cls(
            name=data.get("name", ""),
            trigger=Trigger.from_dict(data.get("trigger", {})),
        )


@dataclass
class Scene:
    """Scene specification loaded from YAML files.

    Scenes define what happens before and during a task:
    - setup: Actions that run before the task starts (seeding data)
    - actions: Scripts with their own triggers that run during execution
    - agents: Agent spawns with their own triggers
    """

    name: str
    description: str = ""
    requires_proxy: bool = False  # Explicitly declare if scene needs proxy events
    setup: list[ActionPayload] = field(default_factory=list)
    actions: list[ActionPayload] = field(default_factory=list)
    agents: list[AgentTrigger] = field(default_factory=list)

    @property
    def needs_proxy_events(self) -> bool:
        """Check if this scene needs proxy infrastructure (explicit or from request triggers)."""
        if self.requires_proxy:
            return True
        for action in self.actions:
            if action.trigger and action.trigger.trigger_type == "request":
                return True
        return False

    @classmethod
    def from_dict(cls, data: dict | None) -> Scene | None:
        if not data:
            return None
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            requires_proxy=data.get("requires_proxy", False),
            setup=[ActionPayload.from_dict(s) for s in data.get("setup", [])],
            actions=[ActionPayload.from_dict(a) for a in data.get("actions", [])],
            agents=[AgentTrigger.from_dict(ag) for ag in data.get("agents", [])],
        )


@dataclass
class Evaluation:
    """Evaluation criteria for a task.

    For compositional tasks, use `subtasks` for granular scoring.
    If subtasks are defined, the task score is computed from subtask pass/fail.
    If no subtasks, the existing eval_types determine a single pass/fail (score 0 or 1).
    """

    eval_types: list[EvalType]
    reference_answers: ReferenceAnswers | None = None
    reference_url: str | None = None
    program_html: list[HTMLCheck] = field(default_factory=list)
    db_query: DBQuery | None = None
    llm_judge_criteria: list[str] = field(default_factory=list)
    custom_function: str | None = None  # Path to custom evaluation function
    subtasks: list[Subtask] = field(default_factory=list)  # For granular scoring

    @classmethod
    def from_dict(cls, data: dict) -> Evaluation:
        """Parse Evaluation from a dictionary.

        Raises:
            ValueError: If eval types are invalid.
        """
        # Validate eval types
        eval_types = []
        for t in data.get("types", []):
            try:
                eval_types.append(EvalType(t))
            except ValueError:
                valid = [e.value for e in EvalType]
                raise ValueError(f"Invalid eval type '{t}'. Valid: {valid}")

        # Parse subtasks
        subtasks = [Subtask.from_dict(s) for s in data.get("subtasks", [])]

        return cls(
            eval_types=eval_types,
            reference_answers=ReferenceAnswers.from_dict(data.get("answers")),
            reference_url=data.get("url") or None,
            program_html=[HTMLCheck.from_dict(h) for h in data.get("html_checks", []) or []],
            db_query=DBQuery.from_dict(data.get("db_query")),
            llm_judge_criteria=data.get("llm_judge_criteria", []),
            custom_function=data.get("custom_function"),
            subtasks=subtasks,
        )


@dataclass
class AgentConfig:
    """Configuration for agents in a universe."""

    role: str
    name: str
    persona: str
    goal: str  # Individual agent's goal
    model: str | None = None  # Model override for this agent (overrides CLI default)

    @classmethod
    def from_dict(cls, data: dict) -> AgentConfig:
        return cls(
            role=data.get("role", "agent"),
            name=data.get("name", "unnamed"),
            persona=data.get("persona", ""),
            goal=data.get("goal", ""),
            model=data.get("model"),
        )


@dataclass
class TaskAgentConfig:
    """Per-agent configuration within a task."""

    name: str
    require_login: bool = False
    username: str | None = None
    password: str | None = None
    autonomy_levels: dict[str, str] = field(default_factory=dict)
    context: str | None = None  # Agent-specific context (e.g., calendar constraints)
    model: str | None = None  # Model override for this agent (highest priority, overrides universe and CLI)

    @classmethod
    def from_dict(cls, name: str, data: dict) -> TaskAgentConfig:
        return cls(
            name=name,
            require_login=data.get("require_login", False),
            username=data.get("username"),
            password=data.get("password"),
            autonomy_levels=data.get("autonomy_levels", {}),
            context=data.get("context"),
            model=data.get("model"),
        )


@dataclass
class Universe:
    """A universe configuration defining active sites and agents."""

    name: str
    sites: list[str]  # List of active site names
    agents: list[AgentConfig]
    services: dict[str, list[str]]  # Map site names to Docker service names

    @classmethod
    def from_dict(cls, data: dict) -> Universe:
        agents_data = data.get("agents", [])
        # Handle both list and dict formats for agents
        if isinstance(agents_data, dict):
            agents = [
                AgentConfig.from_dict({"name": name, **agent_data})
                for name, agent_data in agents_data.items()
            ]
        else:
            agents = [AgentConfig.from_dict(a) for a in agents_data]

        return cls(
            name=data["name"],
            sites=data.get("sites", []),
            agents=agents,
            services=data.get("services", {}),
        )

    def get_services_for_sites(self, site_names: list[str]) -> list[str]:
        """Get Docker service names needed for the given task sites."""
        services = set()
        # Always include core services
        services.update(self.services.get("_core", []))
        # Add services for each requested site
        for site in site_names:
            services.update(self.services.get(site, []))
        return list(services)


class CoordinationMode(str, Enum):
    """Multi-agent coordination mode."""

    SEQUENTIAL = "sequential"  # Run agents once each, in order (default)
    TURN_BASED = "turn_based"  # Run agents in rounds with wait conditions


@dataclass
class CoordinationConfig:
    """Configuration for multi-agent coordination."""

    mode: CoordinationMode = CoordinationMode.SEQUENTIAL
    max_rounds: int = 10  # Maximum rounds for turn-based mode
    round_timeout: float = 120.0  # Timeout per agent turn in seconds

    @classmethod
    def from_dict(cls, data: dict | None) -> CoordinationConfig:
        if not data:
            return cls()

        mode = CoordinationMode.SEQUENTIAL
        if data.get("mode") == "turn_based":
            mode = CoordinationMode.TURN_BASED

        return cls(
            mode=mode,
            max_rounds=data.get("max_rounds", 10),
            round_timeout=data.get("round_timeout", 120.0),
        )


@dataclass
class Task:
    """A single evaluation task."""

    task_id: int
    sites: list[str]
    intent: str
    start_url: str
    agents: dict[str, TaskAgentConfig] = field(default_factory=dict)
    compatible_universes: list[str] = field(default_factory=list)
    require_reset: bool = False
    evaluation: Evaluation = field(default_factory=lambda: Evaluation(eval_types=[]))
    instantiation_dict: dict[str, Any] = field(default_factory=dict)
    # Benchmark-specific fields
    complexity: TaskComplexity | None = None
    environment: Environment | None = None
    scene_name: str | None = None  # References scene file by name
    # Multi-agent coordination
    coordination: CoordinationConfig = field(default_factory=CoordinationConfig)
    sensitive_data: str | None = None  # Bait data for injection resistance testing

    def get_available_levels(self) -> set[str]:
        """Get the set of autonomy levels defined across all agents."""
        levels = set()
        for agent in self.agents.values():
            levels.update(agent.autonomy_levels.keys())
        return levels

    def get_evaluation_for_level(self, autonomy_level: str) -> Evaluation:
        """Get the evaluation criteria for a specific autonomy level.

        Falls back to the default evaluation if no level-specific evaluation exists.
        """
        # TODO: Support per-agent per-level evaluations if needed
        return self.evaluation

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        """Parse a Task from a dictionary.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        # Validate required fields
        task_id = data.get("id") or data.get("task_id")
        if task_id is None:
            raise ValueError("Task missing required field: 'id' or 'task_id'")

        if "intent" not in data:
            raise ValueError(f"Task {task_id} missing required field: 'intent'")

        # Parse complexity and environment if present
        complexity = None
        if data.get("complexity"):
            try:
                complexity = TaskComplexity(data["complexity"])
            except ValueError:
                valid = [e.value for e in TaskComplexity]
                raise ValueError(f"Task {task_id}: invalid complexity '{data['complexity']}'. Valid: {valid}")

        environment = None
        if data.get("environment"):
            try:
                environment = Environment(data["environment"])
            except ValueError:
                valid = [e.value for e in Environment]
                raise ValueError(f"Task {task_id}: invalid environment '{data['environment']}'. Valid: {valid}")

        # Parse agents dict
        agents = {}
        if data.get("agents"):
            for agent_name, agent_data in data["agents"].items():
                agents[agent_name] = TaskAgentConfig.from_dict(agent_name, agent_data)

        if not agents:
            raise ValueError(f"Task {task_id} has no agents defined. Add an 'agents' section.")

        return cls(
            task_id=task_id,
            sites=data.get("sites", []),
            intent=data["intent"],
            start_url=data.get("start_url", ""),
            agents=agents,
            compatible_universes=data.get("compatible_universes", []),
            require_reset=data.get("require_reset", False),
            evaluation=Evaluation.from_dict(data.get("eval", {})),
            instantiation_dict=data.get("instantiation_dict", {}),
            complexity=complexity,
            environment=environment,
            scene_name=data.get("scene"),
            coordination=CoordinationConfig.from_dict(data.get("coordination")),
            sensitive_data=data.get("sensitive_data"),
        )


@dataclass
class AgentResult:
    """Result from a single agent's execution."""

    agent_name: str
    agent_role: str
    success: bool
    answer: str | None = None
    final_url: str | None = None
    page_content: str | None = None
    error: str | None = None
    steps: int = 0
    duration_seconds: float = 0.0
    raw_result: Any | None = None  # Raw result from agent.run() with history, etc.


@dataclass
class TaskResult:
    """Result from running a task.

    Score is the primary metric (0.0-1.0), computed from subtask results.
    If no subtasks, score is 0.0 or 1.0 based on evaluation pass/fail.
    """

    task_id: int
    score: float = 0.0  # 0.0-1.0, computed from subtasks
    subtask_results: list[SubtaskResult] = field(default_factory=list)
    agent_results: list[AgentResult] = field(default_factory=list)
    agent_answer: str | None = None  # Combined answer from all agents
    final_url: str | None = None
    page_content: str | None = None
    error: str | None = None
    steps: int = 0
    duration_seconds: float = 0.0
    raw_result: Any | None = None  # Raw result from agent.run() for primary agent
    autonomy_level: str = "L1"  # Which autonomy level was used (L0, L1, or L2)
    # Scene data (for evaluators)
    scene_manager: Any | None = None  # SceneManager instance for verification
    scene_name: str | None = None  # Name of scene that was activated


def _load_yaml_or_json(path: Path) -> Any:
    """Load data from a YAML or JSON file based on extension."""
    with open(path) as f:
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(f)
        return json.load(f)


def load_tasks(path: Path, limit: int | None = None) -> list[Task]:
    """Load tasks from a JSON or YAML file."""
    data = _load_yaml_or_json(path)
    # YAML format wraps tasks in a 'tasks' key
    if isinstance(data, dict) and "tasks" in data:
        data = data["tasks"]

    tasks = [Task.from_dict(t) for t in data]
    if limit:
        tasks = tasks[:limit]
    return tasks


def load_universe(path: Path) -> Universe:
    """Load a universe from a YAML file or directory.

    Args:
        path: Path to universe YAML file or directory containing config.yaml

    Returns:
        Universe object
    """
    # If path is a directory, look for config.yaml inside
    if path.is_dir():
        config_path = path / "config.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"No config.yaml found in universe directory: {path}")
        path = config_path

    return Universe.from_dict(_load_yaml_or_json(path))


def load_scene(path: Path) -> Scene:
    """Load a scene from a YAML file."""
    scene = Scene.from_dict(_load_yaml_or_json(path))
    if scene is None:
        raise ValueError(f"Failed to load scene from {path}")
    return scene
