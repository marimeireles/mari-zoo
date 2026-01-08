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
class Evaluation:
    """Evaluation criteria for a task."""

    eval_types: list[EvalType]
    reference_answers: ReferenceAnswers | None = None
    reference_url: str | None = None
    program_html: list[HTMLCheck] = field(default_factory=list)
    db_query: DBQuery | None = None

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

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        # Support both old format (task_id) and new format (id)
        task_id = data.get("id") if "id" in data else data.get("task_id")

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
