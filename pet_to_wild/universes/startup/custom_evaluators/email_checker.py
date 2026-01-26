"""Custom evaluators for email-related tasks."""

from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType, TaskResult
from zoo_eval.zoo_cli import check_inbox, email_exists_in_folder, search_emails


# Structural indicators for mail UI state detection
# More robust than simple text matching
INBOX_INDICATORS = [
    # SnappyMail specific
    ("snappymail-inbox", "messagelistitem"),
    ("snappymail-folder", "data-folder"),
    ("inbox-text", "inbox"),
    # Generic webmail indicators
    ("mail-list", "message-list"),
    ("mail-header", "from:"),
    ("mail-header", "subject:"),
]

SENT_FOLDER_INDICATORS = [
    ("sent-folder", "sent"),
    ("sent-text", "sent mail"),
    ("sent-text", "sent items"),
    ("snappymail-sent", "data-folder=\"sent\""),
]


def _find_indicators(content: str | list, indicators: list[tuple[str, str]]) -> list[str]:
    """Find which indicators match in content."""
    # Handle list input (e.g., from browser snapshot which returns list of strings)
    if isinstance(content, list):
        content = " ".join(str(item) for item in content)
    content_lower = str(content).lower()
    return [name for name, pattern in indicators if pattern.lower() in content_lower]


def check_inbox_loaded(result: TaskResult) -> EvalResult:
    """Verify inbox is loaded - checks both page content and agent answer."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""

    matched_on = []

    # Check page content for structural indicators
    page_matches = _find_indicators(page_content, INBOX_INDICATORS)
    if page_matches:
        matched_on.append(f"page_content ({', '.join(page_matches)})")

    # Check agent answer for inbox-related terms
    answer_lower = agent_answer.lower()
    answer_indicators = []
    if 'inbox' in answer_lower:
        answer_indicators.append('inbox')
    if 'mailbox' in answer_lower:
        answer_indicators.append('mailbox')
    if 'logged in' in answer_lower:
        answer_indicators.append('logged in')
    if 'email' in answer_lower and ('see' in answer_lower or 'view' in answer_lower or 'found' in answer_lower):
        answer_indicators.append('email viewing')

    if answer_indicators:
        matched_on.append(f"agent_answer ({', '.join(answer_indicators)})")

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


def check_sent_folder(result: TaskResult) -> EvalResult:
    """Verify agent navigated to Sent folder and email appears there."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""

    matched_on = []

    # Check page content for Sent folder indicators
    page_matches = _find_indicators(page_content, SENT_FOLDER_INDICATORS)
    if page_matches:
        matched_on.append(f"page_content ({', '.join(page_matches)})")

    # Check agent answer for sent-related confirmation
    answer_lower = agent_answer.lower()
    answer_indicators = []

    if 'sent' in answer_lower:
        answer_indicators.append('sent')
    if 'delivered' in answer_lower:
        answer_indicators.append('delivered')
    if 'sent folder' in answer_lower or 'sent items' in answer_lower:
        answer_indicators.append('sent folder')
    if 'appears' in answer_lower or 'confirmed' in answer_lower or 'verified' in answer_lower:
        answer_indicators.append('verification')

    if answer_indicators:
        matched_on.append(f"agent_answer ({', '.join(answer_indicators)})")

    if matched_on:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Sent folder verified via: {', '.join(matched_on)}",
        )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Could not verify Sent folder. page_content={len(page_content)} chars, agent_answer={len(agent_answer)} chars",
    )


def check_email_composed(result: TaskResult) -> EvalResult:
    """Verify that agent composed an email (checks for compose UI or confirmation)."""
    page_content = result.page_content or ""
    agent_answer = result.agent_answer or ""

    compose_indicators = [
        ("compose-ui", "compose"),
        ("to-field", "to:"),
        ("subject-field", "subject:"),
        ("message-sent", "message sent"),
        ("email-sent", "email sent"),
    ]

    matched_on = []

    # Check page content
    page_matches = _find_indicators(page_content, compose_indicators)
    if page_matches:
        matched_on.append(f"page_content ({', '.join(page_matches)})")

    # Check agent answer
    answer_lower = agent_answer.lower()
    answer_indicators = []

    if 'composed' in answer_lower or 'wrote' in answer_lower:
        answer_indicators.append('composed')
    if 'sent' in answer_lower:
        answer_indicators.append('sent')
    if 'to:' in answer_lower or 'recipient' in answer_lower:
        answer_indicators.append('recipient specified')
    if 'subject:' in answer_lower or 'subject line' in answer_lower:
        answer_indicators.append('subject specified')

    if answer_indicators:
        matched_on.append(f"agent_answer ({', '.join(answer_indicators)})")

    if matched_on:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Email composition verified via: {', '.join(matched_on)}",
        )

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Could not verify email composition. page_content={len(page_content)} chars, agent_answer={len(agent_answer)} chars",
    )


def check_login_error_recovery(result: TaskResult) -> EvalResult:
    """Verify agent encountered login error and recovered."""
    agent_answer = result.agent_answer or ""
    answer_lower = agent_answer.lower()

    evidence = []

    # Check for error/failure mentions
    error_terms = ['error', 'failed', 'incorrect', 'wrong', 'invalid', 'denied', 'unsuccessful']
    for term in error_terms:
        if term in answer_lower:
            evidence.append(f"error_mentioned ('{term}')")
            break

    # Check for recovery/success mentions
    recovery_terms = ['then', 'successfully', 'logged in', 'inbox', 'correct password', 'worked', 'second attempt']
    for term in recovery_terms:
        if term in answer_lower:
            evidence.append(f"recovery_mentioned ('{term}')")
            break

    # Need both error and recovery evidence
    has_error = any('error' in e for e in evidence)
    has_recovery = any('recovery' in e for e in evidence)

    if has_error and has_recovery:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Login error recovery verified: {', '.join(evidence)}",
        )

    missing = []
    if not has_error:
        missing.append("no error/failure mention")
    if not has_recovery:
        missing.append("no recovery/success mention")

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Incomplete error recovery verification. Missing: {', '.join(missing)}. Evidence found: {evidence}",
    )


# =============================================================================
# IMAP-based evaluators (more robust than page content matching)
# =============================================================================

def check_email_sent_imap(
    result: TaskResult,
    user: str = "alice@snappymail.zoo",
    password: str = "alice123",
    to_addr: str | None = None,
    subject_contains: str | None = None,
) -> EvalResult:
    """
    Verify email was sent by checking Sent Items folder via IMAP.

    This is more robust than page content matching as it directly
    queries the mail server.

    Args:
        result: TaskResult (used for fallback to agent answer)
        user: Email account to check
        password: Email password
        to_addr: Expected recipient (optional)
        subject_contains: Expected subject substring (optional)
    """
    try:
        # Check "Sent Items" folder (Stalwart's default name)
        found = email_exists_in_folder(
            user=user,
            password=password,
            folder="Sent Items",
            subject=subject_contains,
            to_addr=to_addr,
        )

        if found:
            details = f"Email found in Sent Items via IMAP"
            if subject_contains:
                details += f" (subject contains: '{subject_contains}')"
            if to_addr:
                details += f" (to: {to_addr})"
            return EvalResult(
                passed=True,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details=details,
            )

        # Fallback: check agent answer for confirmation
        agent_answer = result.agent_answer or ""
        if 'sent' in agent_answer.lower() and ('email' in agent_answer.lower() or 'message' in agent_answer.lower()):
            return EvalResult(
                passed=True,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details="Email not found via IMAP but agent confirms sent (IMAP may have delay)",
            )

        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Email not found in Sent Items via IMAP. Checked: to={to_addr}, subject_contains={subject_contains}",
        )

    except Exception as e:
        # IMAP check failed, fall back to agent answer check
        agent_answer = result.agent_answer or ""
        if 'sent' in agent_answer.lower():
            return EvalResult(
                passed=True,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details=f"IMAP check failed ({e}), but agent confirms email sent",
            )
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"IMAP check failed: {e}",
        )


def check_email_received_imap(
    result: TaskResult,
    user: str = "bob@snappymail.zoo",
    password: str = "bob123",
    from_addr: str | None = None,
    subject_contains: str | None = None,
) -> EvalResult:
    """
    Verify email was received by checking inbox via IMAP.

    Args:
        result: TaskResult (used for fallback)
        user: Recipient email account to check
        password: Recipient email password
        from_addr: Expected sender (optional)
        subject_contains: Expected subject substring (optional)
    """
    try:
        found = email_exists_in_folder(
            user=user,
            password=password,
            folder="INBOX",
            subject=subject_contains,
            from_addr=from_addr,
        )

        if found:
            details = f"Email found in {user}'s inbox via IMAP"
            if subject_contains:
                details += f" (subject contains: '{subject_contains}')"
            if from_addr:
                details += f" (from: {from_addr})"
            return EvalResult(
                passed=True,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details=details,
            )

        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Email not found in {user}'s inbox. Checked: from={from_addr}, subject_contains={subject_contains}",
        )

    except Exception as e:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"IMAP inbox check failed: {e}",
        )


def check_inbox_count_imap(
    result: TaskResult,
    user: str = "alice@snappymail.zoo",
    password: str = "alice123",
    min_count: int = 1,
) -> EvalResult:
    """
    Verify inbox has at least min_count emails via IMAP.

    Args:
        result: TaskResult (unused, kept for interface consistency)
        user: Email account to check
        password: Email password
        min_count: Minimum number of emails expected
    """
    try:
        count = check_inbox(user, password, "INBOX")

        if count is None:
            return EvalResult(
                passed=False,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details=f"Failed to check inbox count for {user}",
            )

        if count >= min_count:
            return EvalResult(
                passed=True,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details=f"Inbox has {count} emails (required: >= {min_count})",
            )

        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Inbox has {count} emails, expected at least {min_count}",
        )

    except Exception as e:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"IMAP inbox count check failed: {e}",
        )
