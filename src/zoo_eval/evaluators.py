"""Evaluators for different eval types."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .models import Evaluation, EvalType, TaskResult


@dataclass
class EvalResult:
    """Result of an evaluation."""

    passed: bool
    eval_type: EvalType
    details: str = ""


class Evaluator(ABC):
    """Base class for evaluators."""

    @abstractmethod
    def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
        """Evaluate a task result against criteria."""
        pass


class StringMatchEvaluator(Evaluator):
    """Evaluates string matching criteria."""

    def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
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

        # Exact match
        if ref.exact_match:
            expected = ref.exact_match.lower().strip()
            if answer == expected or expected in answer:
                return EvalResult(
                    passed=True,
                    eval_type=EvalType.STRING_MATCH,
                    details=f"Exact match: '{ref.exact_match}'",
                )

        # Must include all
        if ref.must_include:
            missing = [s for s in ref.must_include if s.lower() not in answer]
            if not missing:
                return EvalResult(
                    passed=True,
                    eval_type=EvalType.STRING_MATCH,
                    details=f"Includes all required: {ref.must_include}",
                )
            return EvalResult(
                passed=False,
                eval_type=EvalType.STRING_MATCH,
                details=f"Missing: {missing}",
            )

        # Fuzzy match - all must be present (normalized)
        if ref.fuzzy_match:
            normalized_answer = re.sub(r"\s+", "", answer)
            missing = []
            for s in ref.fuzzy_match:
                normalized_s = re.sub(r"\s+", "", s.lower())
                if normalized_s not in normalized_answer:
                    missing.append(s)
            if not missing:
                return EvalResult(
                    passed=True,
                    eval_type=EvalType.STRING_MATCH,
                    details=f"Fuzzy match: {ref.fuzzy_match}",
                )
            return EvalResult(
                passed=False,
                eval_type=EvalType.STRING_MATCH,
                details=f"Missing fuzzy: {missing}",
            )

        return EvalResult(
            passed=False,
            eval_type=EvalType.STRING_MATCH,
            details="No matching criteria met",
        )


class URLMatchEvaluator(Evaluator):
    """Evaluates URL matching criteria."""

    def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
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

        # Normalize URLs for comparison
        actual = result.final_url.rstrip("/").lower()
        expected = evaluation.reference_url.rstrip("/").lower()

        # Check if expected URL pattern is in actual (GOLD in PRED)
        if expected in actual:
            return EvalResult(
                passed=True,
                eval_type=EvalType.URL_MATCH,
                details=f"URL contains expected: {evaluation.reference_url}",
            )

        return EvalResult(
            passed=False,
            eval_type=EvalType.URL_MATCH,
            details=f"URL mismatch: got '{result.final_url}', expected '{evaluation.reference_url}'",
        )


class ProgramHTMLEvaluator(Evaluator):
    """Evaluates HTML content on the page."""

    def evaluate(self, result: TaskResult, evaluation: Evaluation) -> EvalResult:
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


def get_evaluator(eval_type: EvalType) -> Evaluator:
    """Get the appropriate evaluator for an eval type."""
    evaluators = {
        EvalType.STRING_MATCH: StringMatchEvaluator(),
        EvalType.URL_MATCH: URLMatchEvaluator(),
        EvalType.PROGRAM_HTML: ProgramHTMLEvaluator(),
    }
    return evaluators[eval_type]


def evaluate_task(result: TaskResult, evaluation: Evaluation) -> list[EvalResult]:
    """Run all evaluators for a task and return results."""
    results = []
    for eval_type in evaluation.eval_types:
        evaluator = get_evaluator(eval_type)
        results.append(evaluator.evaluate(result, evaluation))
    return results
