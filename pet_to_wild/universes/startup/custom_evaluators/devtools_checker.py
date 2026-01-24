"""Custom evaluators for devtools tasks (Kanban, Gitea)."""

from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType, TaskResult


def check_focalboard_logged_in(result: TaskResult) -> EvalResult:
    """Check if user successfully logged into Kanban (Focalboard)."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""

    # Focalboard shows "Boards" or user's boards after login
    login_indicators = ["Boards", "Dashboard", "Create a Board", "Templates"]

    for indicator in login_indicators:
        if indicator in page_content or indicator in agent_answer:
            return EvalResult(
                passed=True,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details=f"Successfully logged into Kanban (found: {indicator})",
            )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details="Kanban login not verified - dashboard indicators not found",
    )


def check_gitea_logged_in(result: TaskResult) -> EvalResult:
    """Check if user successfully logged into Gitea."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""

    # Gitea shows these after login
    login_indicators = ["Dashboard", "My Repositories", "Organizations", "Sign Out", "New Repository"]

    for indicator in login_indicators:
        if indicator in page_content or indicator in agent_answer:
            return EvalResult(
                passed=True,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details=f"Successfully logged into Gitea (found: {indicator})",
            )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details="Gitea login not verified - dashboard indicators not found",
    )
