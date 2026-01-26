"""Custom evaluators for multi-agent coordination tasks."""

import re
from dataclasses import dataclass
from typing import Optional

from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType, TaskResult


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


def verify_3way_meeting(result: TaskResult) -> EvalResult:
    """
    Verify that Alice, Bob, and Charlie successfully negotiated a meeting time.

    Checks that the agreed time works for all three calendars.
    """
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

    proposed_times = _parse_meeting_time(combined_answer)

    if not proposed_times:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="No meeting time could be parsed from agent answers",
        )

    valid_times = []
    invalid_reasons = []

    for day, hour in proposed_times:
        alice_ok = _is_valid_for_calendar(day, hour, ALICE_CALENDAR_3WAY)
        bob_ok = _is_valid_for_calendar(day, hour, BOB_CALENDAR_3WAY)
        charlie_ok = _is_valid_for_calendar(day, hour, CHARLIE_CALENDAR)

        if alice_ok and bob_ok and charlie_ok:
            valid_times.append(f"{day} {hour}:00")
        else:
            reasons = []
            if not alice_ok:
                reasons.append("not in Alice's calendar")
            if not bob_ok:
                reasons.append("not in Bob's calendar")
            if not charlie_ok:
                reasons.append("not in Charlie's calendar")
            invalid_reasons.append(f"{day} {hour}:00 ({', '.join(reasons)})")

    if valid_times:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Valid 3-way meeting time agreed: {valid_times[0]}",
        )

    mutual_slots = _find_valid_mutual_times([ALICE_CALENDAR_3WAY, BOB_CALENDAR_3WAY, CHARLIE_CALENDAR])
    mutual_str = [f"{s.day} {s.start_hour}:00-{s.end_hour}:00" for s in mutual_slots]

    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"No valid mutual time for all 3. Times found: {invalid_reasons}. Valid options were: {mutual_str}",
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
