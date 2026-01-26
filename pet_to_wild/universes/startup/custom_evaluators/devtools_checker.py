"""Custom evaluators for devtools tasks (Kanban, Gitea)."""

import re

from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType, TaskResult


# Focalboard (Kanban) UI indicators
FOCALBOARD_LOGGED_IN_INDICATORS = [
    ("boards-text", "boards"),
    ("dashboard", "dashboard"),
    ("create-board", "create a board"),
    ("templates", "templates"),
    ("workspace", "workspace"),
]

FOCALBOARD_CARD_INDICATORS = [
    ("card-created", "created"),
    ("card-added", "added"),
    ("new-card", "new card"),
    ("card-title", "q1 metrics"),  # From task 205
]

# Gitea UI indicators
GITEA_LOGGED_IN_INDICATORS = [
    ("dashboard", "dashboard"),
    ("my-repos", "my repositories"),
    ("sign-out", "sign out"),
    ("new-repo", "new repository"),
    ("organizations", "organizations"),
]

GITEA_ISSUE_INDICATORS = [
    ("issue-created", "issue #"),
    ("issue-created", "created issue"),
    ("issue-created", "new issue"),
]


def _check_indicators(content: str | list, indicators: list[tuple[str, str]]) -> list[str]:
    """Check which indicators are present in content."""
    # Handle list input (e.g., from browser snapshot which returns list of strings)
    if isinstance(content, list):
        content = " ".join(str(item) for item in content)
    content_lower = str(content).lower()
    return [name for name, pattern in indicators if pattern.lower() in content_lower]


def check_focalboard_logged_in(result: TaskResult) -> EvalResult:
    """Check if user successfully logged into Kanban (Focalboard)."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""
    combined = page_content + " " + agent_answer

    matched = _check_indicators(combined, FOCALBOARD_LOGGED_IN_INDICATORS)

    if matched:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Successfully logged into Kanban (found: {', '.join(matched)})",
        )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Kanban login not verified - dashboard indicators not found. page_content={len(page_content)} chars, agent_answer={len(agent_answer)} chars",
    )


def check_gitea_logged_in(result: TaskResult) -> EvalResult:
    """Check if user successfully logged into Gitea."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""
    combined = page_content + " " + agent_answer

    matched = _check_indicators(combined, GITEA_LOGGED_IN_INDICATORS)

    if matched:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Successfully logged into Gitea (found: {', '.join(matched)})",
        )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Gitea login not verified - dashboard indicators not found. page_content={len(page_content)} chars, agent_answer={len(agent_answer)} chars",
    )


def check_kanban_card_created(result: TaskResult) -> EvalResult:
    """Check if a Kanban card was created."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""
    combined = page_content + " " + agent_answer

    evidence = []

    # Check for card creation indicators
    matched = _check_indicators(combined, FOCALBOARD_CARD_INDICATORS)
    if matched:
        evidence.extend(matched)

    # Check agent answer for explicit confirmation
    answer_lower = agent_answer.lower()
    if 'created' in answer_lower and ('card' in answer_lower or 'task' in answer_lower):
        evidence.append("agent_confirms_creation")
    if 'added' in answer_lower and ('card' in answer_lower or 'board' in answer_lower):
        evidence.append("agent_confirms_add")
    if 'successfully' in answer_lower:
        evidence.append("success_mentioned")

    if evidence:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Kanban card creation verified: {', '.join(evidence)}",
        )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Could not verify card creation. No creation indicators found.",
    )


def check_gitea_issue_created(result: TaskResult) -> EvalResult:
    """Check if a Gitea issue was created."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""
    combined = page_content + " " + agent_answer

    evidence = []

    # Check for issue number pattern (#1, #2, etc.)
    issue_pattern = r'#\d+'
    issues_found = re.findall(issue_pattern, combined)
    if issues_found:
        evidence.append(f"issue_numbers: {', '.join(issues_found[:3])}")

    # Check for creation indicators
    combined_lower = combined.lower()
    if 'created' in combined_lower and 'issue' in combined_lower:
        evidence.append("issue_created")
    if 'new issue' in combined_lower:
        evidence.append("new_issue")
    if 'submitted' in combined_lower:
        evidence.append("submitted")

    # Check for edit/label indicators
    if 'label' in combined_lower:
        evidence.append("label_mentioned")
    if 'edited' in combined_lower or 'updated' in combined_lower:
        evidence.append("issue_edited")
    if 'enhancement' in combined_lower:
        evidence.append("enhancement_label")

    if evidence:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Gitea issue creation verified: {', '.join(evidence)}",
        )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Could not verify issue creation. No issue indicators found.",
    )


def check_pr_created(result: TaskResult) -> EvalResult:
    """Check if a pull request was created."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""
    combined = page_content + " " + agent_answer
    combined_lower = combined.lower()

    evidence = []

    # Check for PR indicators
    if 'pull request' in combined_lower or 'merge request' in combined_lower:
        evidence.append("pr_mentioned")
    if 'pr #' in combined_lower or 'pr#' in combined_lower:
        evidence.append("pr_number")
    if 'created' in combined_lower and ('pr' in combined_lower or 'pull' in combined_lower):
        evidence.append("pr_created")
    if 'submitted' in combined_lower:
        evidence.append("submitted")

    # Check for PR URL patterns
    pr_pattern = r'/pulls?/\d+'
    prs_found = re.findall(pr_pattern, combined)
    if prs_found:
        evidence.append(f"pr_urls: {len(prs_found)}")

    if evidence:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Pull request creation verified: {', '.join(evidence)}",
        )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Could not verify PR creation. No PR indicators found.",
    )


def check_repo_forked(result: TaskResult) -> EvalResult:
    """Check if a repository was forked."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""
    combined = page_content + " " + agent_answer
    combined_lower = combined.lower()

    evidence = []

    # Check for fork indicators
    if 'forked' in combined_lower:
        evidence.append("forked_mentioned")
    if 'fork of' in combined_lower or 'forked from' in combined_lower:
        evidence.append("fork_relationship")
    if 'your fork' in combined_lower or 'my fork' in combined_lower:
        evidence.append("fork_ownership")

    # Check for commit indicators
    if 'committed' in combined_lower or 'commit' in combined_lower:
        evidence.append("commit_mentioned")
    if 'pushed' in combined_lower:
        evidence.append("pushed")

    # Check for the specific change mentioned in task
    if 'charlie' in combined_lower and ('readme' in combined_lower or 'forked by' in combined_lower):
        evidence.append("expected_change")

    if evidence:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Fork operation verified: {', '.join(evidence)}",
        )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Could not verify fork operation. No fork indicators found.",
    )
