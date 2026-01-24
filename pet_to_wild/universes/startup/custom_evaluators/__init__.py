"""Custom evaluation functions for benchmark tasks.

This module contains user-defined evaluation functions that can be referenced
in task configurations.

Each function should:
- Accept a TaskResult as its only parameter
- Return an EvalResult
- Inspect result.page_content, result.agent_answer, etc.
- Implement custom verification logic

Example:
    def my_custom_check(result: TaskResult) -> EvalResult:
        from zoo_eval.evaluators import EvalResult
        from zoo_eval.models import EvalType

        if "expected text" in result.page_content:
            return EvalResult(
                passed=True,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details="Found expected content on page"
            )
        else:
            return EvalResult(
                passed=False,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details="Expected content not found"
            )
"""

from .email_checker import check_inbox_loaded
from .devtools_checker import check_focalboard_logged_in, check_gitea_logged_in

__all__ = ["check_inbox_loaded", "check_focalboard_logged_in", "check_gitea_logged_in"]
