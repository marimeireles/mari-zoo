"""Data models for tasks and evaluations."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RunConfig:
    """Configuration for task runs."""

    max_steps: int = 30
    timeout_seconds: float = 120.0  # 2 minutes default
    headless: bool = True
    save_traces: bool = True
    trace_dir: str = "./traces"
    model: str = "google/gemini-2.5-flash-lite"  # Model to use via OpenRouter
    shared_browser: bool = False  # If True, all agents share the same browser and memory


class EvalType(str, Enum):
    STRING_MATCH = "string_match"
    URL_MATCH = "url_match"
    PROGRAM_HTML = "program_html"
    DB_MATCH = "db_match"
    LLM_JUDGE = "llm_judge"
    HUMAN_CRITIC = "human_critic"


class TaskComplexity(str, Enum):
    """Task complexity levels."""

    ATOMIC = "atomic"
    COMPOSITIONAL = "compositional"
    OPEN_ENDED = "open_ended"


class Environment(str, Enum):
    """Environment adversarial conditions."""

    DOMESTICATED = "domesticated"
    URBAN = "urban"
    WILD = "wild"


@dataclass
class ReferenceAnswers:
    """Expected answers for string matching."""

    exact_match: str | None = None
    must_include: list[str] = field(default_factory=list)
    fuzzy_match: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> ReferenceAnswers | None:
        if not data:
            return None
        return cls(
            exact_match=data.get("exact_match"),
            must_include=data.get("must_include", []),
            fuzzy_match=data.get("fuzzy_match", []),
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
    """Trigger specification for when a scene activates."""

    trigger_type: str  # "time" | "event" | "page_load" (only "time" supported for now)
    delay: int | None = None  # For time triggers: seconds after task starts
    event_name: str | None = None  # For event triggers (future)
    url_pattern: str | None = None  # For page_load triggers (future)

    @classmethod
    def from_dict(cls, data: dict) -> Trigger:
        return cls(
            trigger_type=data.get("type", "time"),
            delay=data.get("delay"),
            event_name=data.get("event_name"),
            url_pattern=data.get("url_pattern"),
        )


@dataclass
class InjectionPayload:
    """Adversarial injection payload for a scene."""

    injection_type: str  # "email" | "webpage" | "database"
    location: str  # e.g., "inbox", "product_page"
    content: str  # The injection text (or email body)
    attacker_goal: str  # e.g., "email_sent_to_attacker", "exfiltrate_data"
    from_email: str = ""  # Sender email for email injections
    subject: str = ""  # Email subject for email injections
    body: str = ""  # Email body (alternative to content)

    @classmethod
    def from_dict(cls, data: dict) -> InjectionPayload:
        return cls(
            injection_type=data.get("type", "email"),
            location=data.get("location", ""),
            content=data.get("content", ""),
            attacker_goal=data.get("attacker_goal", ""),
            from_email=data.get("from_email", ""),
            subject=data.get("subject", ""),
            body=data.get("body", data.get("content", "")),
        )


@dataclass
class Scene:
    """Adversarial scene specification loaded from separate YAML files."""

    name: str
    description: str = ""
    triggers: list[Trigger] = field(default_factory=list)
    injections: list[InjectionPayload] = field(default_factory=list)
    noise_level: str = "clean"  # "clean" | "low" | "high"
    spam_count: int = 0  # Number of spam emails for urban environments

    @classmethod
    def from_dict(cls, data: dict | None) -> Scene | None:
        if not data:
            return None
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            triggers=[Trigger.from_dict(t) for t in data.get("triggers", [])],
            injections=[InjectionPayload.from_dict(i) for i in data.get("injections", [])],
            noise_level=data.get("noise_level", "clean"),
            spam_count=data.get("spam_count", 0),
        )


@dataclass
class SecurityCheck:
    """Security check specification."""

    check_type: str  # e.g., "no_email_to_domain", "no_data_leak"
    params: dict[str, Any] = field(default_factory=dict)  # Check-specific parameters

    @classmethod
    def from_dict(cls, data: dict) -> SecurityCheck:
        return cls(
            check_type=data.get("type", ""),
            params={k: v for k, v in data.items() if k != "type"},
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
    security_checks: list[SecurityCheck] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> Evaluation:
        # Support both old format (eval_types) and new format (types)
        types_key = "types" if "types" in data else "eval_types"
        answers_key = "answers" if "answers" in data else "reference_answers"
        url_key = "url" if "url" in data else "reference_url"
        html_key = "html_checks" if "html_checks" in data else "program_html"

        return cls(
            eval_types=[EvalType(t) for t in data.get(types_key, [])],
            reference_answers=ReferenceAnswers.from_dict(data.get(answers_key)),
            reference_url=data.get(url_key) or None,
            program_html=[HTMLCheck.from_dict(h) for h in data.get(html_key, []) or []],
            db_query=DBQuery.from_dict(data.get("db_query")),
            llm_judge_criteria=data.get("llm_judge_criteria", []),
            security_checks=[
                SecurityCheck.from_dict(s) for s in data.get("security_checks", [])
            ],
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
class Universe:
    """A universe configuration defining active sites and agents."""

    name: str
    sites: list[str]  # List of active site names
    agents: list[AgentConfig]

    @classmethod
    def from_dict(cls, data: dict) -> Universe:
        agents_data = data.get("agents", [])
        agents = [AgentConfig.from_dict(a) for a in agents_data]

        return cls(
            name=data["name"],
            sites=data.get("sites", []),
            agents=agents,
        )


@dataclass
class Task:
    """A single evaluation task."""

    task_id: int
    sites: list[str]
    intent: str
    start_url: str
    compatible_universes: list[str] = field(default_factory=list)
    require_login: bool = False
    require_reset: bool = False
    storage_state: str | None = None
    evaluation: Evaluation = field(default_factory=lambda: Evaluation(eval_types=[]))
    instantiation_dict: dict[str, Any] = field(default_factory=dict)
    # Benchmark-specific fields
    complexity: TaskComplexity | None = None
    environment: Environment | None = None
    autonomy_levels: dict[str, str] = field(default_factory=dict)  # L0, L1, L2
    policies: list[str] = field(default_factory=list)
    scene_name: str | None = None  # References scene file by name

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        # Support both old format (task_id) and new format (id)
        task_id = data.get("id") if "id" in data else data.get("task_id")

        # Parse complexity and environment if present
        complexity = None
        if data.get("complexity"):
            complexity = TaskComplexity(data["complexity"])

        environment = None
        if data.get("environment"):
            environment = Environment(data["environment"])

        return cls(
            task_id=task_id,
            sites=data.get("sites", []),
            intent=data["intent"],
            start_url=data.get("start_url", ""),
            compatible_universes=data.get("compatible_universes", []),
            require_login=data.get("require_login", False),
            require_reset=data.get("require_reset", False),
            storage_state=data.get("storage_state"),
            evaluation=Evaluation.from_dict(data.get("eval", {})),
            instantiation_dict=data.get("instantiation_dict", {}),
            complexity=complexity,
            environment=environment,
            autonomy_levels=data.get("autonomy_levels", {}),
            policies=data.get("policies", []),
            scene_name=data.get("scene"),
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
    """Load a universe from a YAML file."""
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
