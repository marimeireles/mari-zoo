"""Custom evaluators for email-related tasks."""

from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType, TaskResult


def check_inbox_loaded(result: TaskResult) -> EvalResult:
    # Check page HTML content (captured via CDP hook)
    if 'Inbox' in result.page_content:
            return EvalResult(
                passed=True,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details="Successfully logged into inbox",
            )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details="Error in loading agent's history or action failed.",
    )
