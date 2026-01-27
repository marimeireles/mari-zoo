"""Data models for tasks and evaluations."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


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
    judge_model: str = "gpt-4o"  # Model for LLM judge evaluation (auto-detects provider)
    shared_browser: bool = False  # If True, all agents share the same browser and memory
    autonomy_levels: list[str] = field(default_factory=lambda: ["L1"])  # Which levels to run (L0, L1, L2)
    completed_pairs: set[tuple[int, str]] = field(default_factory=set)  # (task_id, level) pairs to skip (for resume)
    harness: AgentHarness = AgentHarness.BROWSER_USE  # Which agent harness to use
    claude_model: str = "sonnet"  # Claude model for Claude SDK harness ("opus", "sonnet", "haiku")
    skip_zoo_reset: bool = False  # If True, skip Docker restart/reset (assume services are ready)


class EvalType(str, Enum):
    STRING_MATCH = "string_match"
    URL_MATCH = "url_match"
    PROGRAM_HTML = "program_html"
    DB_MATCH = "db_match"
    LLM_JUDGE = "llm_judge"
    HUMAN_CRITIC = "human_critic"
    CUSTOM_FUNCTION = "custom_function"  # User-defined Python function for custom evaluation logic


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
    must_include: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> ReferenceAnswers | None:
        if not data:
            return None
        return cls(
            exact_match=data.get("exact_match"),
            must_include=data.get("must_include", []),
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
    - event: Activate when a Matomo event is detected
    - page_load: Activate immediately before agent starts

    Event trigger fields (for type="event"):
    - site: Zoo site domain (e.g., 'gitea.zoo')
    - event_category: Matomo event category (e.g., 'AJAX', 'Button', 'Form')
    - event_match: Text to match in event name (case-insensitive)
    - timeout: Max seconds to wait for event (default: 600)
    """

    trigger_type: str  # "time" | "event" | "page_load"
    delay: int | None = None  # For time triggers: seconds after task starts
    # Event trigger fields
    site: str | None = None  # Zoo site domain
    event_category: str | None = None  # Matomo event category
    event_match: str | None = None  # Text to match in event name
    timeout: float = 600.0  # Max seconds to wait for event triggers (default: 10 minutes)

    @classmethod
    def from_dict(cls, data: dict) -> Trigger:
        return cls(
            trigger_type=data.get("type", "time"),
            delay=data.get("delay"),
            site=data.get("site"),
            event_category=data.get("event_category"),
            event_match=data.get("event_match"),
            timeout=data.get("timeout", 600.0),
        )


@dataclass
class ActionPayload:
    """Action that runs as part of a scene.

    Actions are scripts or commands that execute during a scene. They can run:
    - In setup: before the task starts (e.g., seeding a database, creating repos)
    - On triggers: during task execution when conditions are met (e.g., sending an email)
    """

    action_type: str  # "script"
    script_path: str = ""  # Path to Python script to execute
    description: str = ""  # Optional description of the action

    @classmethod
    def from_dict(cls, data: dict) -> ActionPayload:
        return cls(
            action_type=data.get("type", "script"),
            script_path=data.get("script_path", ""),
            description=data.get("description", ""),
        )


@dataclass
class Scene:
    """Scene specification loaded from YAML files.

    Scenes define what happens before and during a task:
    - setup: Actions that run before the task starts (seeding data)
    - triggers: Conditions that activate actions during execution
    - actions: What runs when triggers fire
    """

    name: str
    description: str = ""
    setup: list[ActionPayload] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    actions: list[ActionPayload] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> Scene | None:
        if not data:
            return None
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            setup=[ActionPayload.from_dict(s) for s in data.get("setup", [])],
            triggers=[Trigger.from_dict(t) for t in data.get("triggers", [])],
            actions=[ActionPayload.from_dict(a) for a in data.get("actions", [])],
        )


@dataclass
class Evaluation:
    """Evaluation criteria for a task."""

    eval_types: list[EvalType]
    reference_answers: ReferenceAnswers | None = None
    reference_url: str | None = None
    program_html: list[HTMLCheck] = field(default_factory=list)
    db_query: DBQuery | None = None
    llm_judge_criteria: list[str] = field(default_factory=list)
    custom_function: str | None = None  # Path to custom evaluation function (e.g., "custom_evaluators.email_checker")

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

        return cls(
            eval_types=eval_types,
            reference_answers=ReferenceAnswers.from_dict(data.get("answers")),
            reference_url=data.get("url") or None,
            program_html=[HTMLCheck.from_dict(h) for h in data.get("html_checks", []) or []],
            db_query=DBQuery.from_dict(data.get("db_query")),
            llm_judge_criteria=data.get("llm_judge_criteria", []),
            custom_function=data.get("custom_function"),
        )


@dataclass
class AgentConfig:
    """Configuration for agents in a universe."""

    role: str
    name: str
    persona: str
    goal: str  # Individual agent's goal

    @classmethod
    def from_dict(cls, data: dict) -> AgentConfig:
        return cls(
            role=data["role"],
            name=data["name"],
            persona=data["persona"],
            goal=data["goal"],
        )


@dataclass
class TaskAgentConfig:
    """Per-agent configuration within a task."""

    name: str
    require_login: bool = False
    username: str | None = None
    password: str | None = None
    autonomy_levels: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: dict) -> TaskAgentConfig:
        return cls(
            name=name,
            require_login=data.get("require_login", False),
            username=data.get("username"),
            password=data.get("password"),
            autonomy_levels=data.get("autonomy_levels", {}),
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
    """Result from running a task."""

    task_id: int
    success: bool
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


def load_tasks(path: Path, limit: int | None = None) -> list[Task]:
    """Load tasks from a JSON or YAML file."""
    with open(path) as f:
        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(f)
            # YAML format wraps tasks in a 'tasks' key
            if isinstance(data, dict) and "tasks" in data:
                data = data["tasks"]
        else:
            data = json.load(f)

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

    with open(path) as f:
        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(f)
        else:
            data = json.load(f)

    return Universe.from_dict(data)


def load_scene(path: Path) -> Scene:
    """Load a scene from a YAML file."""
    with open(path) as f:
        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(f)
        else:
            data = json.load(f)

    scene = Scene.from_dict(data)
    if scene is None:
        raise ValueError(f"Failed to load scene from {path}")
    return scene
