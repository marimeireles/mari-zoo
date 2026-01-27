"""Custom evaluators for multi-agent coordination tasks."""

import re
from dataclasses import dataclass
from typing import Optional

from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType, TaskResult
from zoo_eval.zoo_cli import email_exists_in_folder, search_emails, get_email_body, get_email_headers


@dataclass
class TimeSlot:
    """Represents a time slot."""
    day: str
    start_hour: int
    end_hour: int

    def contains(self, day: str, hour: int) -> bool:
        """Check if this slot contains the given day and hour."""
        return self.day.lower() == day.lower() and self.start_hour <= hour < self.end_hour

    def overlaps(self, other: "TimeSlot") -> Optional["TimeSlot"]:
        """Return overlapping slot if days match, None otherwise."""
        if self.day.lower() != other.day.lower():
            return None
        start = max(self.start_hour, other.start_hour)
        end = min(self.end_hour, other.end_hour)
        if start < end:
            return TimeSlot(self.day, start, end)
        return None


# Calendar constraints for task 301
ALICE_CALENDAR = [
    TimeSlot("Monday", 9, 12),
    TimeSlot("Monday", 14, 17),  # 2pm-5pm
    TimeSlot("Wednesday", 10, 15),  # 10am-3pm
    TimeSlot("Thursday", 13, 17),  # 1pm-5pm
    TimeSlot("Friday", 14, 17),  # 2pm-5pm
]

BOB_CALENDAR = [
    TimeSlot("Monday", 15, 24),  # 3pm onwards
    TimeSlot("Tuesday", 9, 12),
    TimeSlot("Wednesday", 0, 24),  # All day
    TimeSlot("Friday", 9, 13),  # 9am-1pm
]

# Calendar constraints for task 302 (3-way)
ALICE_CALENDAR_3WAY = [
    TimeSlot("Monday", 9, 12),
    TimeSlot("Monday", 14, 17),
    TimeSlot("Wednesday", 10, 15),
    TimeSlot("Thursday", 13, 17),
]

BOB_CALENDAR_3WAY = [
    TimeSlot("Monday", 15, 24),
    TimeSlot("Tuesday", 9, 12),
    TimeSlot("Wednesday", 0, 24),
    TimeSlot("Friday", 9, 13),
]

CHARLIE_CALENDAR = [
    TimeSlot("Monday", 10, 16),  # 10am-4pm
    TimeSlot("Tuesday", 14, 17),  # 2pm-5pm
    TimeSlot("Wednesday", 9, 13),  # 9am-1pm
    TimeSlot("Friday", 0, 24),  # All day
]


def _parse_meeting_time(text: str) -> list[tuple[str, int]]:
    """
    Extract potential meeting times from text.

    Returns list of (day, hour) tuples found.
    """
    text_lower = text.lower()
    results = []

    # Day patterns
    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]

    # Time patterns: "3pm", "3:00pm", "15:00", "3 pm", "3:00 PM"
    time_patterns = [
        r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)',  # 3pm, 3:00pm
        r'(\d{1,2}):(\d{2})',  # 15:00
    ]

    for day in days:
        if day in text_lower:
            # Look for times near this day mention
            day_idx = text_lower.find(day)
            context = text_lower[max(0, day_idx - 50):day_idx + 100]

            for pattern in time_patterns:
                matches = re.findall(pattern, context)
                for match in matches:
                    hour = int(match[0])
                    if len(match) > 2 and match[2]:  # Has am/pm
                        if match[2] == 'pm' and hour != 12:
                            hour += 12
                        elif match[2] == 'am' and hour == 12:
                            hour = 0
                    results.append((day.capitalize(), hour))

    return results


def _is_valid_for_calendar(day: str, hour: int, calendar: list[TimeSlot]) -> bool:
    """Check if a time is valid for a calendar."""
    for slot in calendar:
        if slot.contains(day, hour):
            return True
    return False


def _find_valid_mutual_times(calendars: list[list[TimeSlot]]) -> list[TimeSlot]:
    """Find all time slots that work for all calendars."""
    if not calendars:
        return []

    # Start with first calendar's slots
    valid = calendars[0].copy()

    # Intersect with each subsequent calendar
    for calendar in calendars[1:]:
        new_valid = []
        for slot in valid:
            for other_slot in calendar:
                overlap = slot.overlaps(other_slot)
                if overlap:
                    new_valid.append(overlap)
        valid = new_valid

    return valid


def verify_meeting_negotiated(result: TaskResult) -> EvalResult:
    """
    Verify that Alice and Bob successfully negotiated a meeting time.

    Checks:
    1. A specific day and time was mentioned
    2. The time is valid for Alice's calendar
    3. The time is valid for Bob's calendar
    """
    # Combine all agent answers
    combined_answer = ""
    if result.agent_results:
        for agent_result in result.agent_results:
            if agent_result.answer:
                combined_answer += f"\n[{agent_result.agent_name}]: {agent_result.answer}"
    else:
        combined_answer = result.agent_answer or ""

    if not combined_answer:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="No agent answers to evaluate",
        )

    # Parse meeting times from answers
    proposed_times = _parse_meeting_time(combined_answer)

    if not proposed_times:
        # Try to find any day+time pattern even without structured format
        answer_lower = combined_answer.lower()
        evidence = []

        # Check for agreement language
        agreement_phrases = ["agreed", "confirmed", "let's meet", "works for me", "see you"]
        has_agreement = any(phrase in answer_lower for phrase in agreement_phrases)
        if has_agreement:
            evidence.append("agreement_language_found")

        # Check for specific days mentioned
        days_mentioned = [d for d in ["monday", "tuesday", "wednesday", "thursday", "friday"]
                         if d in answer_lower]
        if days_mentioned:
            evidence.append(f"days_mentioned: {days_mentioned}")

        if evidence:
            return EvalResult(
                passed=False,
                eval_type=EvalType.CUSTOM_FUNCTION,
                details=f"Could not parse specific time. Evidence: {evidence}. Need day + hour format.",
            )

        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="No meeting time could be parsed from agent answers",
        )

    # Check each proposed time against both calendars
    valid_times = []
    invalid_reasons = []

    for day, hour in proposed_times:
        alice_ok = _is_valid_for_calendar(day, hour, ALICE_CALENDAR)
        bob_ok = _is_valid_for_calendar(day, hour, BOB_CALENDAR)

        if alice_ok and bob_ok:
            valid_times.append(f"{day} {hour}:00")
        else:
            reasons = []
            if not alice_ok:
                reasons.append("not in Alice's calendar")
            if not bob_ok:
                reasons.append("not in Bob's calendar")
            invalid_reasons.append(f"{day} {hour}:00 ({', '.join(reasons)})")

    if valid_times:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Valid meeting time agreed: {valid_times[0]}. All valid times found: {valid_times}",
        )

    # Calculate what valid times would have been
    mutual_slots = _find_valid_mutual_times([ALICE_CALENDAR, BOB_CALENDAR])
    mutual_str = [f"{s.day} {s.start_hour}:00-{s.end_hour}:00" for s in mutual_slots]

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"No valid mutual time agreed. Times found: {invalid_reasons}. Valid options were: {mutual_str}",
    )


def _verify_emails_exchanged_imap(
    alice_user: str = "alice@snappymail.zoo",
    alice_pass: str = "alice123",
    bob_user: str = "bob@snappymail.zoo",
    bob_pass: str = "bob123",
    include_content: bool = False,
) -> tuple[bool, list[str], dict[str, str]]:
    """
    Verify emails were exchanged via IMAP.

    Args:
        include_content: If True, also fetch and return email bodies

    Returns:
        (success, details, email_contents) - success is True if both parties exchanged emails
        email_contents is a dict with keys like "alice_to_bob", "bob_to_alice"
    """
    details = []
    email_contents = {}

    # Check Bob received email from Alice
    try:
        uids = search_emails(
            user=bob_user,
            password=bob_pass,
            folder="INBOX",
            from_addr="alice",
        )
        alice_to_bob = len(uids) > 0
        if alice_to_bob:
            details.append(f"✓ Alice→Bob: {len(uids)} email(s) found in Bob's INBOX")
            if include_content and uids:
                # Get the latest email
                latest_uid = uids[-1]
                headers = get_email_headers(bob_user, bob_pass, latest_uid)
                body = get_email_body(bob_user, bob_pass, latest_uid)
                email_contents["alice_to_bob"] = {
                    "subject": headers.get("Subject", ""),
                    "body": body[:500] if body else "",
                }
        else:
            details.append("✗ No email from Alice found in Bob's INBOX")
    except Exception as e:
        details.append(f"✗ Failed to check Bob's inbox: {e}")
        alice_to_bob = False

    # Check Alice received reply from Bob
    try:
        uids = search_emails(
            user=alice_user,
            password=alice_pass,
            folder="INBOX",
            from_addr="bob",
        )
        bob_to_alice = len(uids) > 0
        if bob_to_alice:
            details.append(f"✓ Bob→Alice: {len(uids)} email(s) found in Alice's INBOX")
            if include_content and uids:
                latest_uid = uids[-1]
                headers = get_email_headers(alice_user, alice_pass, latest_uid)
                body = get_email_body(alice_user, alice_pass, latest_uid)
                email_contents["bob_to_alice"] = {
                    "subject": headers.get("Subject", ""),
                    "body": body[:500] if body else "",
                }
        else:
            details.append("✗ No email from Bob found in Alice's INBOX")
    except Exception as e:
        details.append(f"✗ Failed to check Alice's inbox: {e}")
        bob_to_alice = False

    return (alice_to_bob and bob_to_alice, details, email_contents)


def verify_meeting_negotiated_with_imap(result: TaskResult, task=None, show_emails: bool = True) -> EvalResult:
    """
    Verify meeting negotiation using IMAP + LLM.

    Flow:
    1. IMAP: Verify emails were exchanged and fetch content
    2. LLM: Judge if a valid meeting time was agreed based on email content + calendar constraints

    This is more robust than regex parsing - the LLM understands natural language.

    Args:
        result: TaskResult from agent execution
        task: Task object containing agent configs with context (calendar constraints)
        show_emails: Whether to include email content in output details
    """
    from zoo_eval.llm import create_openai_client

    # First verify emails were actually exchanged via IMAP
    imap_success, imap_details, email_contents = _verify_emails_exchanged_imap(include_content=True)

    all_details = []
    all_details.append("=== IMAP Verification ===")
    all_details.extend(imap_details)

    if not imap_success:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="\n".join(all_details) + "\n\nFailed: Emails were not exchanged.",
        )

    # Build email content for LLM
    email_text = ""
    if "alice_to_bob" in email_contents:
        email = email_contents["alice_to_bob"]
        email_text += f"Alice's email to Bob:\nSubject: {email.get('subject', 'N/A')}\n{email.get('body', '')}\n\n"
    if "bob_to_alice" in email_contents:
        email = email_contents["bob_to_alice"]
        email_text += f"Bob's email to Alice:\nSubject: {email.get('subject', 'N/A')}\n{email.get('body', '')}\n\n"

    if show_emails:
        all_details.append("")
        all_details.append("=== Email Content ===")
        all_details.append(email_text[:500] + "..." if len(email_text) > 500 else email_text)

    # Extract calendar constraints from task agent contexts
    agent_contexts = {}
    if task and hasattr(task, 'agents'):
        for agent_name, agent_config in task.agents.items():
            if hasattr(agent_config, 'context') and agent_config.context:
                agent_contexts[agent_name] = agent_config.context

    # Build calendar constraints section for LLM
    if agent_contexts:
        calendar_section = "CALENDAR CONSTRAINTS (from task definition):\n"
        for agent_name, context in agent_contexts.items():
            calendar_section += f"\n{agent_name.upper()}'s constraints:\n{context}\n"
        all_details.append("")
        all_details.append("=== Using Calendar from Task YAML ===")
    else:
        # Fallback to hardcoded if no task context available
        calendar_section = """CALENDAR CONSTRAINTS:
- Alice is free: Monday 9am-12pm, Monday 2pm-5pm, Wednesday 10am-3pm, Thursday 1pm-5pm, Friday 2pm-5pm
- Bob is free: Monday 3pm onwards, Tuesday 9am-12pm, Wednesday all day, Friday 9am-1pm"""
        all_details.append("")
        all_details.append("=== Using Fallback Calendar (no task context) ===")

    # Use LLM to evaluate
    prompt = f"""You are evaluating whether two people successfully agreed on a meeting time via email.

{calendar_section}

EMAIL EXCHANGE:
{email_text}

EVALUATE:
1. Did they agree on a specific day and time?
2. If yes, does that time work for BOTH participants based on their calendar constraints above?

Respond with JSON:
{{
  "agreed_time": "the agreed day and time, or null if none",
  "valid_for_all": true/false,
  "passed": true/false,
  "reasoning": "brief explanation including which constraints were checked"
}}"""

    try:
        client, model = create_openai_client("gpt-4o")
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )

        import json
        llm_result = json.loads(response.choices[0].message.content)

        all_details.append("")
        all_details.append("=== LLM Evaluation ===")
        all_details.append(f"Agreed time: {llm_result.get('agreed_time', 'None')}")
        all_details.append(f"Valid for all: {llm_result.get('valid_for_all', 'N/A')}")
        all_details.append(f"Reasoning: {llm_result.get('reasoning', 'N/A')}")

        passed = llm_result.get("passed", False)

        return EvalResult(
            passed=passed,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="\n".join(all_details),
        )

    except Exception as e:
        all_details.append(f"\nLLM evaluation error: {e}")
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="\n".join(all_details),
        )


def verify_3way_meeting(result: TaskResult, task=None) -> EvalResult:
    """
    Verify that Alice, Bob, and Charlie successfully negotiated a meeting time.

    Uses LLM to evaluate based on calendar constraints from task context.

    Args:
        result: TaskResult from agent execution
        task: Task object containing agent configs with context (calendar constraints)
    """
    from zoo_eval.llm import create_openai_client

    combined_answer = ""
    if result.agent_results:
        for agent_result in result.agent_results:
            if agent_result.answer:
                combined_answer += f"\n[{agent_result.agent_name}]: {agent_result.answer}"
    else:
        combined_answer = result.agent_answer or ""

    if not combined_answer:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="No agent answers to evaluate",
        )

    all_details = []

    # Extract calendar constraints from task agent contexts
    agent_contexts = {}
    if task and hasattr(task, 'agents'):
        for agent_name, agent_config in task.agents.items():
            if hasattr(agent_config, 'context') and agent_config.context:
                agent_contexts[agent_name] = agent_config.context

    # Build calendar constraints section for LLM
    if agent_contexts:
        calendar_section = "CALENDAR CONSTRAINTS (from task definition):\n"
        for agent_name, context in agent_contexts.items():
            calendar_section += f"\n{agent_name.upper()}'s constraints:\n{context}\n"
        all_details.append("=== Using Calendar from Task YAML ===")
    else:
        # Fallback to hardcoded if no task context available
        calendar_section = """CALENDAR CONSTRAINTS:
- Alice: Monday 9am-12pm, 2pm-5pm; Wednesday 10am-3pm; Thursday 1pm-5pm
- Bob: Monday 3pm onwards; Tuesday 9am-12pm; Wednesday all day; Friday 9am-1pm
- Charlie: Monday 10am-4pm; Tuesday 2pm-5pm; Wednesday 9am-1pm; Friday all day"""
        all_details.append("=== Using Fallback Calendar (no task context) ===")

    # Use LLM to evaluate
    prompt = f"""You are evaluating whether three people successfully agreed on a meeting time.

{calendar_section}

AGENT OUTPUTS:
{combined_answer}

EVALUATE:
1. Did all three agents agree on a specific day and time?
2. If yes, does that time work for ALL THREE participants based on their calendar constraints above?

Respond with JSON:
{{
  "agreed_time": "the agreed day and time, or null if none",
  "valid_for_all": true/false,
  "passed": true/false,
  "reasoning": "brief explanation including which constraints were checked"
}}"""

    try:
        client, model = create_openai_client("gpt-4o")
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )

        import json
        llm_result = json.loads(response.choices[0].message.content)

        all_details.append("")
        all_details.append("=== LLM Evaluation ===")
        all_details.append(f"Agreed time: {llm_result.get('agreed_time', 'None')}")
        all_details.append(f"Valid for all: {llm_result.get('valid_for_all', 'N/A')}")
        all_details.append(f"Reasoning: {llm_result.get('reasoning', 'N/A')}")

        passed = llm_result.get("passed", False)

        return EvalResult(
            passed=passed,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="\n".join(all_details),
        )

    except Exception as e:
        all_details.append(f"\nLLM evaluation error: {e}")
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="\n".join(all_details),
        )


def count_email_exchanges(result: TaskResult) -> dict:
    """
    Analyze email exchange patterns from agent results.

    Returns metrics about the negotiation process.
    """
    metrics = {
        "total_messages": 0,
        "messages_per_agent": {},
        "negotiation_rounds": 0,
    }

    if not result.agent_results:
        return metrics

    for agent_result in result.agent_results:
        name = agent_result.agent_name
        # Count tool calls that look like email operations
        steps = agent_result.steps
        metrics["messages_per_agent"][name] = steps
        metrics["total_messages"] += steps

    # Estimate rounds (each agent taking a turn = 1 round)
    if len(result.agent_results) >= 2:
        metrics["negotiation_rounds"] = min(
            metrics["messages_per_agent"].get(name, 0)
            for name in metrics["messages_per_agent"]
        )

    return metrics
