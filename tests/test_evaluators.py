"""Tests for zoo_eval.evaluators."""

import pytest
from zoo_eval.evaluators import (
    StringMatchEvaluator,
    URLMatchEvaluator,
    EvalResult,
)
from zoo_eval.models import (
    TaskResult,
    AgentResult,
    Evaluation,
    EvalType,
    ReferenceAnswers,
)


def make_task_result(answer: str | None = None, final_url: str | None = None) -> TaskResult:
    """Helper to create a TaskResult for testing."""
    return TaskResult(
        task_id=1,
        success=True,
        agent_answer=answer,
        final_url=final_url,
    )


def make_evaluation(
    eval_types: list[EvalType],
    exact_match: str | None = None,
    must_include: list[str] | None = None,
    reference_url: str | None = None,
) -> Evaluation:
    """Helper to create an Evaluation for testing."""
    ref_answers = None
    if exact_match or must_include:
        ref_answers = ReferenceAnswers(
            exact_match=exact_match,
            must_include=must_include or [],
        )
    return Evaluation(
        eval_types=eval_types,
        reference_answers=ref_answers,
        reference_url=reference_url,
    )


class TestStringMatchEvaluator:
    """Tests for StringMatchEvaluator."""

    @pytest.fixture
    def evaluator(self):
        return StringMatchEvaluator()

    @pytest.mark.asyncio
    async def test_exact_match_pass(self, evaluator):
        """Exact match should pass when answer equals expected."""
        result = make_task_result(answer="hello world")
        evaluation = make_evaluation([EvalType.STRING_MATCH], exact_match="hello world")

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is True
        assert eval_result.eval_type == EvalType.STRING_MATCH

    @pytest.mark.asyncio
    async def test_exact_match_case_insensitive(self, evaluator):
        """Exact match should be case insensitive."""
        result = make_task_result(answer="Hello World")
        evaluation = make_evaluation([EvalType.STRING_MATCH], exact_match="hello world")

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is True

    @pytest.mark.asyncio
    async def test_exact_match_fail(self, evaluator):
        """Exact match should fail when answer differs."""
        result = make_task_result(answer="goodbye world")
        evaluation = make_evaluation([EvalType.STRING_MATCH], exact_match="hello world")

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is False

    @pytest.mark.asyncio
    async def test_must_include_all_pass(self, evaluator):
        """Must include should pass when all terms present."""
        result = make_task_result(answer="The quick brown fox jumps over the lazy dog")
        evaluation = make_evaluation(
            [EvalType.STRING_MATCH],
            must_include=["quick", "fox", "dog"]
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is True

    @pytest.mark.asyncio
    async def test_must_include_case_insensitive(self, evaluator):
        """Must include should be case insensitive."""
        result = make_task_result(answer="Hello WORLD")
        evaluation = make_evaluation(
            [EvalType.STRING_MATCH],
            must_include=["hello", "world"]
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is True

    @pytest.mark.asyncio
    async def test_must_include_partial_fail(self, evaluator):
        """Must include should fail when any term missing."""
        result = make_task_result(answer="The quick fox")
        evaluation = make_evaluation(
            [EvalType.STRING_MATCH],
            must_include=["quick", "fox", "dog"]
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is False
        assert "dog" in eval_result.details  # Should mention missing term

    @pytest.mark.asyncio
    async def test_no_answer_fails(self, evaluator):
        """Should fail when no agent answer provided."""
        result = make_task_result(answer=None)
        evaluation = make_evaluation([EvalType.STRING_MATCH], exact_match="test")

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is False
        assert "No agent answer" in eval_result.details

    @pytest.mark.asyncio
    async def test_no_reference_fails(self, evaluator):
        """Should fail when no reference answers defined."""
        result = make_task_result(answer="test")
        evaluation = make_evaluation([EvalType.STRING_MATCH])

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is False
        assert "No reference answers" in eval_result.details


class TestURLMatchEvaluator:
    """Tests for URLMatchEvaluator with proper URL parsing."""

    @pytest.fixture
    def evaluator(self):
        return URLMatchEvaluator()

    @pytest.mark.asyncio
    async def test_exact_url_match(self, evaluator):
        """Exact URL should match."""
        result = make_task_result(final_url="https://example.zoo/page")
        evaluation = make_evaluation(
            [EvalType.URL_MATCH],
            reference_url="https://example.zoo/page"
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is True

    @pytest.mark.asyncio
    async def test_trailing_slash_normalized(self, evaluator):
        """URLs with/without trailing slashes should match."""
        result = make_task_result(final_url="https://example.zoo/page/")
        evaluation = make_evaluation(
            [EvalType.URL_MATCH],
            reference_url="https://example.zoo/page"
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is True

    @pytest.mark.asyncio
    async def test_case_insensitive(self, evaluator):
        """URL matching should be case insensitive."""
        result = make_task_result(final_url="https://EXAMPLE.ZOO/Page")
        evaluation = make_evaluation(
            [EvalType.URL_MATCH],
            reference_url="https://example.zoo/page"
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is True

    @pytest.mark.asyncio
    async def test_subpath_match(self, evaluator):
        """Subpath of expected URL should match."""
        result = make_task_result(final_url="https://example.zoo/user/profile")
        evaluation = make_evaluation(
            [EvalType.URL_MATCH],
            reference_url="https://example.zoo/user"
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is True

    @pytest.mark.asyncio
    async def test_similar_path_no_match(self, evaluator):
        """Similar but different path should NOT match (no substring matching)."""
        # This tests the fix for the substring matching bug
        # /users should NOT match expected /user
        result = make_task_result(final_url="https://example.zoo/users")
        evaluation = make_evaluation(
            [EvalType.URL_MATCH],
            reference_url="https://example.zoo/user"
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is False

    @pytest.mark.asyncio
    async def test_different_scheme_no_match(self, evaluator):
        """Different scheme should not match."""
        result = make_task_result(final_url="http://example.zoo/page")
        evaluation = make_evaluation(
            [EvalType.URL_MATCH],
            reference_url="https://example.zoo/page"
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is False

    @pytest.mark.asyncio
    async def test_different_host_no_match(self, evaluator):
        """Different host should not match."""
        result = make_task_result(final_url="https://other.zoo/page")
        evaluation = make_evaluation(
            [EvalType.URL_MATCH],
            reference_url="https://example.zoo/page"
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is False

    @pytest.mark.asyncio
    async def test_no_final_url_fails(self, evaluator):
        """Should fail when no final URL captured."""
        result = make_task_result(final_url=None)
        evaluation = make_evaluation(
            [EvalType.URL_MATCH],
            reference_url="https://example.zoo"
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is False
        assert "No final URL" in eval_result.details

    @pytest.mark.asyncio
    async def test_no_reference_url_fails(self, evaluator):
        """Should fail when no reference URL defined."""
        result = make_task_result(final_url="https://example.zoo")
        evaluation = make_evaluation([EvalType.URL_MATCH])

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is False
        assert "No reference URL" in eval_result.details

    @pytest.mark.asyncio
    async def test_root_path_match(self, evaluator):
        """Root path should match."""
        result = make_task_result(final_url="https://example.zoo/")
        evaluation = make_evaluation(
            [EvalType.URL_MATCH],
            reference_url="https://example.zoo"
        )

        eval_result = await evaluator.evaluate(result, evaluation)
        assert eval_result.passed is True
