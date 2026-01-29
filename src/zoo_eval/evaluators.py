"""Evaluators for different eval types."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse

from .models import Evaluation, EvalType, Subtask, SubtaskResult, TaskResult


@dataclass
class EvalResult:
    """Result of an evaluation."""

    passed: bool
    eval_type: EvalType
    details: str = ""


def _check_must_include(answer: str, required_values: list[str]) -> tuple[list[str], list[str]]:
    """Check which required values are present in the answer.

    Args:
        answer: The answer string to check (should already be lowercased)
        required_values: List of values that must be present

    Returns:
        Tuple of (matched values, missing values)
    """
    matched = [v for v in required_values if v.lower() in answer]
    missing = [v for v in required_values if v.lower() not in answer]
    return matched, missing


def _format_match_result(
    matched: list[str], missing: list[str], eval_type: EvalType
) -> EvalResult:
    """Format a must_include match result into an EvalResult."""
    total = len(matched) + len(missing)
    if not missing:
        return EvalResult(
            passed=True,
            eval_type=eval_type,
            details=f"Includes all {total} required values",
        )
    found = len(matched)
    return EvalResult(
        passed=False,
        eval_type=eval_type,
        details=f"Partial: {found}/{total} ({100*found//total}%). Found: {matched}. Missing: {missing}",
    )


class Evaluator(ABC):
    """Base class for evaluators."""

    @abstractmethod
    async def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
        """Evaluate a task result against criteria."""
        pass


class StringMatchEvaluator(Evaluator):
    """Evaluates string matching criteria."""

    async def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
        if not result.agent_answer:
            return EvalResult(
                passed=False,
                eval_type=EvalType.STRING_MATCH,
                details="No agent answer provided",
            )

        answer = result.agent_answer.lower().strip()
        ref = evaluation.reference_answers

        if not ref:
            return EvalResult(
                passed=False,
                eval_type=EvalType.STRING_MATCH,
                details="No reference answers defined",
            )

        # Exact match - answer must exactly equal the expected value
        if ref.exact_match:
            expected = ref.exact_match.lower().strip()
            if answer == expected:
                return EvalResult(
                    passed=True,
                    eval_type=EvalType.STRING_MATCH,
                    details=f"Exact match: '{ref.exact_match}'",
                )
            else:
                return EvalResult(
                    passed=False,
                    eval_type=EvalType.STRING_MATCH,
                    details=f"Expected exact match '{ref.exact_match}', got '{result.agent_answer}'",
                )

        # Must include all
        if ref.must_include:
            matched, missing = _check_must_include(answer, ref.must_include)
            return _format_match_result(matched, missing, EvalType.STRING_MATCH)

        return EvalResult(
            passed=False,
            eval_type=EvalType.STRING_MATCH,
            details="No matching criteria met",
        )


class URLMatchEvaluator(Evaluator):
    """Evaluates URL matching criteria."""

    async def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
        if not result.final_url:
            return EvalResult(
                passed=False,
                eval_type=EvalType.URL_MATCH,
                details="No final URL captured",
            )

        if not evaluation.reference_url:
            return EvalResult(
                passed=False,
                eval_type=EvalType.URL_MATCH,
                details="No reference URL defined",
            )

        # Parse URLs for proper comparison (avoids false positives from substring matching)
        actual_parsed = urlparse(result.final_url.lower())
        expected_parsed = urlparse(evaluation.reference_url.lower())

        # Normalize paths (remove trailing slashes)
        actual_path = actual_parsed.path.rstrip("/") or "/"
        expected_path = expected_parsed.path.rstrip("/") or "/"

        # Check scheme and netloc match exactly
        scheme_match = actual_parsed.scheme == expected_parsed.scheme
        netloc_match = actual_parsed.netloc == expected_parsed.netloc

        # Path must match exactly or actual must start with expected path + /
        # This allows /user to match /user/profile but not /users
        path_match = (
            actual_path == expected_path
            or actual_path.startswith(expected_path + "/")
        )

        if scheme_match and netloc_match and path_match:
            return EvalResult(
                passed=True,
                eval_type=EvalType.URL_MATCH,
                details=f"URL matches expected: {evaluation.reference_url}",
            )

        return EvalResult(
            passed=False,
            eval_type=EvalType.URL_MATCH,
            details=f"URL mismatch: got '{result.final_url}', expected '{evaluation.reference_url}'",
        )


class ProgramHTMLEvaluator(Evaluator):
    """Evaluates HTML content on the page."""

    async def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
        if not result.page_content:
            return EvalResult(
                passed=False,
                eval_type=EvalType.PROGRAM_HTML,
                details="No page content captured",
            )

        content = result.page_content.lower()

        for check in evaluation.program_html:
            required = check.required_contents.get("must_include", [])
            for req in required:
                if req.lower() not in content:
                    return EvalResult(
                        passed=False,
                        eval_type=EvalType.PROGRAM_HTML,
                        details=f"Missing required content: '{req}'",
                    )

        return EvalResult(
            passed=True,
            eval_type=EvalType.PROGRAM_HTML,
            details="All HTML checks passed",
        )


class DBMatchEvaluator(Evaluator):
    """Evaluates agent answer against database query results."""

    async def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
        from .zoo import get_zoo

        if not result.agent_answer:
            return EvalResult(
                passed=False,
                eval_type=EvalType.DB_MATCH,
                details="No agent answer provided",
            )

        db_query = evaluation.db_query
        if not db_query:
            return EvalResult(
                passed=False,
                eval_type=EvalType.DB_MATCH,
                details="No db_query defined",
            )

        # Run the query (use singleton to avoid creating new Zoo per evaluation)
        zoo = get_zoo()
        try:
            if db_query.db_type == "mysql":
                query_result = zoo.query_mysql(db_query.query, db_query.database)
            else:
                query_result = zoo.query_postgres(db_query.query, db_query.database)
        except Exception as e:
            return EvalResult(
                passed=False,
                eval_type=EvalType.DB_MATCH,
                details=f"Query error: {e}",
            )

        # Parse query results (tab-separated, first row is header)
        lines = query_result.strip().split("\n")
        if len(lines) < 2:
            return EvalResult(
                passed=False,
                eval_type=EvalType.DB_MATCH,
                details=f"Query returned no results. Query: {db_query.query}",
            )

        # Extract values from first column (skip header)
        expected_values = []
        for line in lines[1:]:
            cols = line.split("\t")
            if cols:
                expected_values.append(cols[0].strip())

        answer = result.agent_answer.lower()

        if db_query.match_type == "must_include":
            matched, missing = _check_must_include(answer, expected_values)
            return _format_match_result(matched, missing, EvalType.DB_MATCH)

        elif db_query.match_type == "exact_match":
            if len(expected_values) == 1 and expected_values[0].lower() in answer:
                return EvalResult(
                    passed=True,
                    eval_type=EvalType.DB_MATCH,
                    details=f"Exact match: {expected_values[0]}",
                )
            return EvalResult(
                passed=False,
                eval_type=EvalType.DB_MATCH,
                details=f"Expected '{expected_values[0]}', not found in answer",
            )

        elif db_query.match_type == "count":
            # For count queries, check if the number appears in answer
            if expected_values and expected_values[0] in answer:
                return EvalResult(
                    passed=True,
                    eval_type=EvalType.DB_MATCH,
                    details=f"Count match: {expected_values[0]}",
                )
            return EvalResult(
                passed=False,
                eval_type=EvalType.DB_MATCH,
                details=f"Expected count '{expected_values[0]}', not in answer",
            )

        return EvalResult(
            passed=False,
            eval_type=EvalType.DB_MATCH,
            details=f"Unknown match_type: {db_query.match_type}",
        )


class LLMJudgeEvaluator(Evaluator):
    """Uses LLM to verify semantic correctness of task completion.

    Auto-detects provider based on model name:
    - Models with "/" (e.g., "google/gemini-2.5-flash") → OpenRouter
    - Models without "/" (e.g., "gpt-4o") → OpenAI direct
    """

    def __init__(self, judge_model: str = "gpt-4o"):
        """Initialize with judge model.

        Args:
            judge_model: Model to use for judging (auto-detects provider)
        """
        self.judge_model = judge_model

    async def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
        from .llm import create_openai_client

        if not evaluation.llm_judge_criteria:
            return EvalResult(
                passed=False,
                eval_type=EvalType.LLM_JUDGE,
                details="No LLM judge criteria defined",
            )

        if not result.agent_answer:
            return EvalResult(
                passed=False,
                eval_type=EvalType.LLM_JUDGE,
                details="No agent answer to evaluate",
            )

        # Use auto-detected provider for judging
        try:
            client, model = create_openai_client(self.judge_model)

            # Build prompt with strict criteria-only evaluation
            criteria_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(evaluation.llm_judge_criteria))
            prompt = f"""You are a strict evaluator checking if an agent's output meets specific criteria.

IMPORTANT RULES:
- ONLY check the numbered criteria below. Do NOT add extra requirements.
- Do NOT infer what the original task was or judge anything beyond the criteria.

CRITERIA TO CHECK:
{criteria_text}

AGENT'S OUTPUT:
{result.agent_answer}

Check each numbered criterion. Respond with JSON:
{{
  "passed": true/false,
  "reasoning": "Brief status for each criterion"
}}"""

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )

            # Parse response
            result_json = json.loads(response.choices[0].message.content)
            passed = result_json.get("passed", False)
            reasoning = result_json.get("reasoning", "No reasoning provided")

            return EvalResult(
                passed=passed,
                eval_type=EvalType.LLM_JUDGE,
                details=reasoning,
            )

        except Exception as e:
            return EvalResult(
                passed=False,
                eval_type=EvalType.LLM_JUDGE,
                details=f"LLM judge error: {str(e)}",
            )


class HumanCriticEvaluator(Evaluator):
    """Generates review files for human evaluation."""

    def __init__(self, task, universe_name: str = "unknown"):
        """Initialize with task info for file generation."""
        self.task = task
        self.universe_name = universe_name

    async def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
        """Generate review files for human to evaluate."""
        from datetime import datetime
        from pathlib import Path

        # Create directory structure: human_reviews/{date}/{universe}/{task_id}/
        timestamp = datetime.now().strftime("%Y-%m-%d")
        review_dir = Path("human_reviews") / timestamp / self.universe_name / str(self.task.task_id)
        review_dir.mkdir(parents=True, exist_ok=True)

        # Generate review files
        try:
            # 1. Task description
            task_info = {
                "task_id": self.task.task_id,
                "intent": self.task.intent,
                "complexity": self.task.complexity.value if self.task.complexity else None,
                "environment": self.task.environment.value if self.task.environment else None,
                "start_url": self.task.start_url,
            }
            (review_dir / "task.json").write_text(json.dumps(task_info, indent=2))

            # 2. Agent output
            output_info = {
                "agent_answer": result.agent_answer,
                "final_url": result.final_url,
                "score": result.score,
                "error": result.error,
                "steps": result.steps,
                "duration_seconds": result.duration_seconds,
            }
            (review_dir / "output.json").write_text(json.dumps(output_info, indent=2))

            # 3. Evaluation criteria
            criteria_info = {
                "eval_types": [et.value for et in evaluation.eval_types],
                "llm_judge_criteria": evaluation.llm_judge_criteria,
            }
            (review_dir / "criteria.json").write_text(json.dumps(criteria_info, indent=2))

            # 4. README for human reviewer
            readme = f"""# Human Review Required

**Task ID:** {self.task.task_id}
**Universe:** {self.universe_name}
**Date:** {timestamp}

## Task
{self.task.intent}

**Complexity:** {self.task.complexity.value if self.task.complexity else 'N/A'}
**Environment:** {self.task.environment.value if self.task.environment else 'N/A'}

## Agent Output
{result.agent_answer or 'No answer provided'}

## Review Instructions
1. Review the agent's output in `output.json`
2. Check if it meets the criteria in `criteria.json`
3. Mark your decision in `review.json`:
   ```json
   {{
     "passed": true/false,
     "reviewer": "your_name",
     "notes": "explanation of decision",
     "reviewed_at": "YYYY-MM-DD HH:MM:SS"
   }}
   ```

## Files
- `task.json`: Task specification
- `output.json`: Agent's execution results
- `criteria.json`: Evaluation criteria
- `page_content.html`: Final page HTML (if available)
- `review.json`: **Your review goes here**
"""
            (review_dir / "README.md").write_text(readme)

            # 5. Save page content if available
            if result.page_content:
                (review_dir / "page_content.html").write_text(result.page_content)

            return EvalResult(
                passed=False,  # Pending human review
                eval_type=EvalType.HUMAN_CRITIC,
                details=f"Review files generated at: {review_dir}",
            )

        except Exception as e:
            return EvalResult(
                passed=False,
                eval_type=EvalType.HUMAN_CRITIC,
                details=f"Failed to generate review files: {str(e)}",
            )


class CustomFunctionEvaluator(Evaluator):
    """Executes user-defined custom evaluation functions."""

    async def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
        """Load and execute custom evaluation function."""
        if not evaluation.custom_function:
            return EvalResult(
                passed=False,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details="No custom_function path specified",
            )

        try:
            # Import the custom function dynamically
            # Format: "module.submodule.function_name"
            parts = evaluation.custom_function.rsplit(".", 1)
            if len(parts) != 2:
                return EvalResult(
                    passed=False,
                    eval_type=EvalType.CUSTOM_FUNCTION,
                    details=f"Invalid function path: {evaluation.custom_function}. Expected format: 'module.function_name'",
                )

            module_path, function_name = parts

            # Import the module
            import importlib

            try:
                module = importlib.import_module(module_path)
            except ImportError as e:
                return EvalResult(
                    passed=False,
                    eval_type=EvalType.CUSTOM_FUNCTION,
                    details=f"Failed to import module '{module_path}': {str(e)}",
                )

            # Get the function
            if not hasattr(module, function_name):
                return EvalResult(
                    passed=False,
                    eval_type=EvalType.CUSTOM_FUNCTION,
                    details=f"Function '{function_name}' not found in module '{module_path}'",
                )

            custom_func = getattr(module, function_name)

            # Call the function with result and return its EvalResult
            # Support both sync and async custom functions
            import asyncio

            if asyncio.iscoroutinefunction(custom_func):
                eval_result = await custom_func(result)
            else:
                eval_result = custom_func(result)

            # Validate return type
            if not isinstance(eval_result, EvalResult):
                return EvalResult(
                    passed=False,
                    eval_type=EvalType.CUSTOM_FUNCTION,
                    details=f"Custom function must return EvalResult, got {type(eval_result)}",
                )

            return eval_result

        except Exception as e:
            return EvalResult(
                passed=False,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details=f"Error executing custom function: {str(e)}",
            )


def get_evaluator(
    eval_type: EvalType,
    task=None,
    universe_name: str = "unknown",
    judge_model: str = "gpt-4o",
) -> Evaluator:
    """Get the appropriate evaluator for an eval type.

    Args:
        eval_type: Type of evaluator to create
        task: Task object (required for HUMAN_CRITIC)
        universe_name: Universe name (for HUMAN_CRITIC file organization)
        judge_model: Model to use for LLM_JUDGE (auto-detects provider)
    """
    # Simple evaluators that need no config
    simple_evaluators = {
        EvalType.STRING_MATCH: StringMatchEvaluator,
        EvalType.DB_MATCH: DBMatchEvaluator,
        EvalType.CUSTOM_FUNCTION: CustomFunctionEvaluator,
    }

    if eval_type in simple_evaluators:
        return simple_evaluators[eval_type]()

    if eval_type == EvalType.LLM_JUDGE:
        return LLMJudgeEvaluator(judge_model=judge_model)

    if eval_type == EvalType.HUMAN_CRITIC:
        if task is None:
            raise ValueError("HumanCriticEvaluator requires task parameter")
        return HumanCriticEvaluator(task=task, universe_name=universe_name)

    raise ValueError(f"Unknown eval type: {eval_type}")


def compute_score(subtask_results: list[SubtaskResult]) -> float:
    """Compute task score from subtask results.

    Score = sum(passed_subtask_weights) / sum(all_weights)
    Returns 0.0 if no subtasks.
    """
    if not subtask_results:
        return 0.0

    total_weight = sum(s.weight for s in subtask_results)
    if total_weight == 0:
        return 0.0

    passed_weight = sum(s.weight for s in subtask_results if s.passed)
    return passed_weight / total_weight


def _create_evaluation_for_subtask(subtask: Subtask, parent_eval: Evaluation) -> Evaluation:
    """Create a temporary Evaluation for a single subtask.

    For LLM subtasks, the subtask description becomes the criterion.
    For other types, inherits from parent evaluation config.
    """
    if subtask.eval_type == EvalType.LLM_JUDGE:
        return Evaluation(
            eval_types=[EvalType.LLM_JUDGE],
            llm_judge_criteria=[subtask.description],
        )
    else:
        # For other eval types, use parent evaluation's config
        return Evaluation(
            eval_types=[subtask.eval_type],
            reference_answers=parent_eval.reference_answers,
            reference_url=parent_eval.reference_url,
            program_html=parent_eval.program_html,
            db_query=parent_eval.db_query,
            custom_function=parent_eval.custom_function,
        )


async def evaluate_task(
    result: TaskResult,
    evaluation: Evaluation,
    task=None,
    universe_name: str = "unknown",
    judge_model: str = "gpt-4o",
) -> list[SubtaskResult]:
    """Evaluate a task and return subtask results.

    If subtasks are defined, evaluates each using its eval_type.
    If no subtasks, runs standard eval_types as implicit subtasks.

    Args:
        result: Task execution result
        evaluation: Evaluation criteria
        task: Task object (required for HUMAN_CRITIC evaluator)
        universe_name: Universe name (for file organization)
        judge_model: Model to use for LLM_JUDGE

    Returns:
        List of SubtaskResult (also updates result.subtask_results and result.score)
    """
    subtask_results = []

    if evaluation.subtasks:
        # Evaluate each subtask using the same evaluator pattern
        for subtask in evaluation.subtasks:
            # Create temporary evaluation with subtask's criteria
            subtask_eval = _create_evaluation_for_subtask(subtask, evaluation)

            # Use same evaluator as tasks
            evaluator = get_evaluator(
                subtask.eval_type, task=task, universe_name=universe_name, judge_model=judge_model
            )
            eval_result = await evaluator.evaluate(result, subtask_eval)

            subtask_results.append(SubtaskResult(
                subtask_id=subtask.id,
                description=subtask.description,
                weight=subtask.weight,
                passed=eval_result.passed,
                evidence=eval_result.details,
                eval_type=subtask.eval_type,
            ))
    else:
        # No subtasks - run standard evaluators as implicit subtasks (weight=1 each)
        for eval_type in evaluation.eval_types:
            evaluator = get_evaluator(
                eval_type, task=task, universe_name=universe_name, judge_model=judge_model
            )
            eval_result = await evaluator.evaluate(result, evaluation)

            subtask_results.append(SubtaskResult(
                subtask_id=eval_type.value,
                description=f"{eval_type.value} evaluation",
                weight=1,
                passed=eval_result.passed,
                evidence=eval_result.details,
                eval_type=eval_type,
            ))

    # Compute score and update result
    result.subtask_results = subtask_results
    result.score = compute_score(subtask_results)

    return subtask_results
