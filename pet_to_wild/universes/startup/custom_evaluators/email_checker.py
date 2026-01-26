"""Custom evaluators for email-related tasks."""

from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType, TaskResult


def check_inbox_loaded(result: TaskResult) -> EvalResult:
    # Check page HTML content (captured via CDP hook) or agent answer
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""

    # Check if inbox loaded - either in page content or agent's response
    matched_on = []
    if 'Inbox' in page_content:
        matched_on.append("page_content ('Inbox')")
    if 'inbox' in agent_answer.lower():
        matched_on.append("agent_answer ('inbox')")
    if 'MailBox' in agent_answer:
        matched_on.append("agent_answer ('MailBox')")

    if matched_on:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Inbox verified via: {', '.join(matched_on)}",
        )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Could not verify inbox loaded. page_content={len(page_content)} chars, agent_answer={len(agent_answer)} chars. Preview: {(page_content or agent_answer)[:200]}",
    )
