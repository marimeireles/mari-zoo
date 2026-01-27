"""Tests for custom evaluators in pet_to_wild/universes/startup/custom_evaluators."""

import pytest
import sys
from pathlib import Path

# Add project root to path so we can import the custom evaluators
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from zoo_eval.evaluators import EvalResult
from zoo_eval.models import TaskResult, EvalType

# Import custom evaluators
from pet_to_wild.universes.startup.custom_evaluators.email_checker import (
    check_inbox_loaded,
    check_sent_folder,
    check_email_composed,
    check_login_error_recovery,
)
from pet_to_wild.universes.startup.custom_evaluators.devtools_checker import (
    check_focalboard_logged_in,
    check_gitea_logged_in,
    check_kanban_card_created,
    check_gitea_issue_created,
    check_pr_created,
    check_repo_forked,
)


def make_task_result(
    agent_answer: str | None = None,
    page_content: str | None = None,
    final_url: str | None = None,
) -> TaskResult:
    """Helper to create a TaskResult for testing."""
    return TaskResult(
        task_id=1,
        success=True,
        agent_answer=agent_answer,
        page_content=page_content,
        final_url=final_url,
    )


class TestEmailChecker:
    """Tests for email_checker.py evaluators."""

    class TestCheckInboxLoaded:
        """Tests for check_inbox_loaded."""

        def test_inbox_in_page_content(self):
            """Should pass when 'Inbox' appears in page content."""
            result = make_task_result(page_content="<div>Inbox (3 messages)</div>")
            eval_result = check_inbox_loaded(result)
            assert eval_result.passed is True
            assert "page_content" in eval_result.details

        def test_inbox_in_agent_answer(self):
            """Should pass when agent mentions inbox."""
            result = make_task_result(agent_answer="I have successfully logged in and can see my inbox with 5 emails.")
            eval_result = check_inbox_loaded(result)
            assert eval_result.passed is True
            assert "agent_answer" in eval_result.details

        def test_mailbox_in_agent_answer(self):
            """Should pass when agent mentions mailbox."""
            result = make_task_result(agent_answer="The MailBox is now visible with new messages.")
            eval_result = check_inbox_loaded(result)
            assert eval_result.passed is True

        def test_logged_in_mention(self):
            """Should pass when agent mentions being logged in."""
            result = make_task_result(agent_answer="I am now logged in to the email system.")
            eval_result = check_inbox_loaded(result)
            assert eval_result.passed is True
            assert "logged in" in eval_result.details

        def test_email_viewing_context(self):
            """Should pass when agent mentions seeing/viewing emails."""
            result = make_task_result(agent_answer="I can see 3 new emails in the interface.")
            eval_result = check_inbox_loaded(result)
            assert eval_result.passed is True
            assert "email viewing" in eval_result.details

        def test_no_indicators_fails(self):
            """Should fail when no inbox indicators found."""
            result = make_task_result(
                agent_answer="The page has loaded.",
                page_content="<div>Welcome</div>"
            )
            eval_result = check_inbox_loaded(result)
            assert eval_result.passed is False
            assert "Could not verify" in eval_result.details

        def test_empty_inputs(self):
            """Should fail gracefully with empty inputs."""
            result = make_task_result()
            eval_result = check_inbox_loaded(result)
            assert eval_result.passed is False

    class TestCheckSentFolder:
        """Tests for check_sent_folder."""

        def test_sent_in_page_content(self):
            """Should pass when sent folder visible in page."""
            result = make_task_result(page_content='<div data-folder="sent">Sent Mail</div>')
            eval_result = check_sent_folder(result)
            assert eval_result.passed is True

        def test_agent_confirms_sent(self):
            """Should pass when agent confirms email was sent."""
            result = make_task_result(agent_answer="The email has been sent and I verified it appears in the Sent folder.")
            eval_result = check_sent_folder(result)
            assert eval_result.passed is True
            assert "sent folder" in eval_result.details or "sent" in eval_result.details

        def test_delivered_confirmation(self):
            """Should pass when agent mentions delivery."""
            result = make_task_result(agent_answer="Message was delivered successfully.")
            eval_result = check_sent_folder(result)
            assert eval_result.passed is True

        def test_no_sent_indicators_fails(self):
            """Should fail when no sent indicators found."""
            result = make_task_result(agent_answer="I composed the email.")
            eval_result = check_sent_folder(result)
            assert eval_result.passed is False

    class TestCheckEmailComposed:
        """Tests for check_email_composed."""

        def test_compose_in_page(self):
            """Should pass when compose UI visible."""
            result = make_task_result(page_content="<div>Compose new message</div>")
            eval_result = check_email_composed(result)
            assert eval_result.passed is True

        def test_agent_composed_email(self):
            """Should pass when agent confirms composing."""
            result = make_task_result(agent_answer="I composed an email to Bob and sent it successfully.")
            eval_result = check_email_composed(result)
            assert eval_result.passed is True

        def test_with_recipient_and_subject(self):
            """Should pass when agent mentions To: and Subject:."""
            result = make_task_result(
                agent_answer="To: bob@example.com\nSubject: Meeting request\n\nHi Bob..."
            )
            eval_result = check_email_composed(result)
            assert eval_result.passed is True

        def test_no_composition_indicators(self):
            """Should fail when no compose indicators."""
            result = make_task_result(agent_answer="I read the inbox.")
            eval_result = check_email_composed(result)
            assert eval_result.passed is False

    class TestCheckLoginErrorRecovery:
        """Tests for check_login_error_recovery."""

        def test_error_and_recovery(self):
            """Should pass when both error and recovery mentioned."""
            result = make_task_result(
                agent_answer="First login attempt failed with wrong password. Then I used the correct password and successfully logged in to see the inbox."
            )
            eval_result = check_login_error_recovery(result)
            assert eval_result.passed is True

        def test_incorrect_password_then_success(self):
            """Should pass with 'incorrect' error and success."""
            result = make_task_result(
                agent_answer="The login showed 'incorrect password' error. I then tried alice123 and it worked."
            )
            eval_result = check_login_error_recovery(result)
            assert eval_result.passed is True

        def test_only_error_no_recovery(self):
            """Should fail when error mentioned but no recovery."""
            result = make_task_result(
                agent_answer="The login failed with an error message."
            )
            eval_result = check_login_error_recovery(result)
            assert eval_result.passed is False
            assert "no recovery" in eval_result.details

        def test_only_success_no_error(self):
            """Should fail when success mentioned but no error."""
            result = make_task_result(
                agent_answer="I successfully logged in to the inbox."
            )
            eval_result = check_login_error_recovery(result)
            assert eval_result.passed is False
            assert "no error" in eval_result.details


class TestDevtoolsChecker:
    """Tests for devtools_checker.py evaluators."""

    class TestCheckFocalboardLoggedIn:
        """Tests for check_focalboard_logged_in."""

        def test_boards_in_page(self):
            """Should pass when Boards visible in page."""
            result = make_task_result(page_content="<nav>Boards Dashboard Templates</nav>")
            eval_result = check_focalboard_logged_in(result)
            assert eval_result.passed is True

        def test_dashboard_in_agent_answer(self):
            """Should pass when agent sees dashboard."""
            result = make_task_result(agent_answer="I am now on the Focalboard dashboard.")
            eval_result = check_focalboard_logged_in(result)
            assert eval_result.passed is True

        def test_workspace_visible(self):
            """Should pass when workspace mentioned."""
            result = make_task_result(agent_answer="The workspace is now visible with my boards.")
            eval_result = check_focalboard_logged_in(result)
            assert eval_result.passed is True

        def test_login_page_fails(self):
            """Should fail when still on login page."""
            result = make_task_result(
                page_content="<form>Login to Focalboard</form>",
                agent_answer="I see the login form."
            )
            eval_result = check_focalboard_logged_in(result)
            assert eval_result.passed is False

    class TestCheckGiteaLoggedIn:
        """Tests for check_gitea_logged_in."""

        def test_dashboard_in_page(self):
            """Should pass when Dashboard visible."""
            result = make_task_result(page_content="<title>Dashboard - Gitea</title>")
            eval_result = check_gitea_logged_in(result)
            assert eval_result.passed is True

        def test_my_repositories_visible(self):
            """Should pass when My Repositories visible."""
            result = make_task_result(agent_answer="I can see My Repositories list.")
            eval_result = check_gitea_logged_in(result)
            assert eval_result.passed is True

        def test_sign_out_visible(self):
            """Should pass when Sign Out option visible."""
            result = make_task_result(page_content='<a href="/logout">Sign Out</a>')
            eval_result = check_gitea_logged_in(result)
            assert eval_result.passed is True

        def test_sign_in_page_fails(self):
            """Should fail when on Sign In page."""
            result = make_task_result(
                page_content="<h1>Sign In</h1>",
                agent_answer="I see the login page."
            )
            eval_result = check_gitea_logged_in(result)
            assert eval_result.passed is False

    class TestCheckKanbanCardCreated:
        """Tests for check_kanban_card_created."""

        def test_card_created_confirmation(self):
            """Should pass when agent confirms card creation."""
            result = make_task_result(
                agent_answer="I have created a new card titled 'Review Q1 metrics' on the board."
            )
            eval_result = check_kanban_card_created(result)
            assert eval_result.passed is True

        def test_task_added_confirmation(self):
            """Should pass when agent confirms task added."""
            result = make_task_result(
                agent_answer="Successfully added a new task to the board."
            )
            eval_result = check_kanban_card_created(result)
            assert eval_result.passed is True

        def test_q1_metrics_in_answer(self):
            """Should pass when Q1 metrics title mentioned."""
            result = make_task_result(
                agent_answer="The Q1 metrics card is now visible on the board."
            )
            eval_result = check_kanban_card_created(result)
            assert eval_result.passed is True

        def test_no_creation_indicators(self):
            """Should fail when no creation evidence."""
            result = make_task_result(
                agent_answer="I logged in to Focalboard."
            )
            eval_result = check_kanban_card_created(result)
            assert eval_result.passed is False

    class TestCheckGiteaIssueCreated:
        """Tests for check_gitea_issue_created."""

        def test_issue_number_in_answer(self):
            """Should pass when issue number mentioned."""
            result = make_task_result(
                agent_answer="Created issue #3 for adding unit tests."
            )
            eval_result = check_gitea_issue_created(result)
            assert eval_result.passed is True
            assert "#3" in eval_result.details

        def test_new_issue_created(self):
            """Should pass when new issue creation confirmed."""
            result = make_task_result(
                agent_answer="I created a new issue about unit tests and added the enhancement label."
            )
            eval_result = check_gitea_issue_created(result)
            assert eval_result.passed is True

        def test_label_added(self):
            """Should pass when label mentioned."""
            result = make_task_result(
                agent_answer="Submitted the issue and added the enhancement label."
            )
            eval_result = check_gitea_issue_created(result)
            assert eval_result.passed is True
            assert "label" in eval_result.details or "enhancement" in eval_result.details

        def test_no_issue_evidence(self):
            """Should fail when no issue creation evidence."""
            result = make_task_result(
                agent_answer="Navigated to the repository."
            )
            eval_result = check_gitea_issue_created(result)
            assert eval_result.passed is False

    class TestCheckPRCreated:
        """Tests for check_pr_created."""

        def test_pull_request_mentioned(self):
            """Should pass when pull request mentioned."""
            result = make_task_result(
                agent_answer="I created a pull request with the bug fix."
            )
            eval_result = check_pr_created(result)
            assert eval_result.passed is True

        def test_pr_url_in_content(self):
            """Should pass when PR URL pattern found."""
            result = make_task_result(
                page_content='<a href="/alice/calculator-utils/pulls/5">PR #5</a>'
            )
            eval_result = check_pr_created(result)
            assert eval_result.passed is True

        def test_merge_request_terminology(self):
            """Should pass with 'merge request' terminology."""
            result = make_task_result(
                agent_answer="Submitted a merge request for review."
            )
            eval_result = check_pr_created(result)
            assert eval_result.passed is True

        def test_no_pr_evidence(self):
            """Should fail when no PR evidence."""
            result = make_task_result(
                agent_answer="I edited the file."
            )
            eval_result = check_pr_created(result)
            assert eval_result.passed is False

    class TestCheckRepoForked:
        """Tests for check_repo_forked."""

        def test_forked_mentioned(self):
            """Should pass when fork mentioned."""
            result = make_task_result(
                agent_answer="I forked the calculator-utils repository and made changes."
            )
            eval_result = check_repo_forked(result)
            assert eval_result.passed is True

        def test_fork_relationship(self):
            """Should pass when fork relationship mentioned."""
            result = make_task_result(
                agent_answer="My repository is a fork of alice/calculator-utils."
            )
            eval_result = check_repo_forked(result)
            assert eval_result.passed is True

        def test_commit_after_fork(self):
            """Should pass when commit mentioned with fork context."""
            result = make_task_result(
                agent_answer="Forked the repo and committed the README change."
            )
            eval_result = check_repo_forked(result)
            assert eval_result.passed is True

        def test_charlie_readme_change(self):
            """Should pass when expected change mentioned."""
            result = make_task_result(
                agent_answer="I updated the README with 'Forked by Charlie' and committed."
            )
            eval_result = check_repo_forked(result)
            assert eval_result.passed is True
            assert "expected_change" in eval_result.details

        def test_no_fork_evidence(self):
            """Should fail when no fork evidence."""
            result = make_task_result(
                agent_answer="I cloned the repository."
            )
            eval_result = check_repo_forked(result)
            assert eval_result.passed is False


class TestCoordinationChecker:
    """Tests for coordination_checker.py evaluators."""

    class TestParseMeetingTime:
        """Tests for parsing meeting times from natural language."""

        def test_parse_simple_time(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import _parse_meeting_time
            result = _parse_meeting_time("Let's meet Monday at 3pm")
            assert ("Monday", 15) in result

        def test_parse_morning_time(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import _parse_meeting_time
            result = _parse_meeting_time("Wednesday 10am works for me")
            assert ("Wednesday", 10) in result

        def test_parse_24h_format(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import _parse_meeting_time
            result = _parse_meeting_time("Tuesday at 14:00")
            assert ("Tuesday", 14) in result

        def test_parse_multiple_times(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import _parse_meeting_time
            result = _parse_meeting_time("Monday at 2pm or Wednesday at 11am")
            days = [r[0] for r in result]
            assert "Monday" in days
            assert "Wednesday" in days

    class TestCalendarValidation:
        """Tests for validating times against calendar constraints."""

        def test_alice_monday_morning_valid(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import (
                _is_valid_for_calendar, ALICE_CALENDAR
            )
            assert _is_valid_for_calendar("Monday", 10, ALICE_CALENDAR) is True

        def test_alice_tuesday_invalid(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import (
                _is_valid_for_calendar, ALICE_CALENDAR
            )
            assert _is_valid_for_calendar("Tuesday", 10, ALICE_CALENDAR) is False

        def test_bob_monday_afternoon_valid(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import (
                _is_valid_for_calendar, BOB_CALENDAR
            )
            assert _is_valid_for_calendar("Monday", 15, BOB_CALENDAR) is True

        def test_bob_monday_morning_invalid(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import (
                _is_valid_for_calendar, BOB_CALENDAR
            )
            assert _is_valid_for_calendar("Monday", 10, BOB_CALENDAR) is False

        def test_mutual_wednesday_valid(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import (
                _is_valid_for_calendar, ALICE_CALENDAR, BOB_CALENDAR
            )
            assert _is_valid_for_calendar("Wednesday", 11, ALICE_CALENDAR) is True
            assert _is_valid_for_calendar("Wednesday", 11, BOB_CALENDAR) is True

    class TestVerifyMeetingNegotiated:
        """Tests for 2-way meeting negotiation verification."""

        def test_valid_wednesday_meeting(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_meeting_negotiated
            result = make_task_result(
                agent_answer="[alice]: I'll send Bob a meeting request\n[bob]: Wednesday at 11am works perfectly!"
            )
            eval_result = verify_meeting_negotiated(result)
            assert eval_result.passed is True
            assert "Wednesday" in eval_result.details

        def test_valid_monday_afternoon(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_meeting_negotiated
            result = make_task_result(agent_answer="We agreed to meet Monday at 4pm.")
            eval_result = verify_meeting_negotiated(result)
            assert eval_result.passed is True

        def test_invalid_tuesday_meeting(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_meeting_negotiated
            result = make_task_result(agent_answer="Let's meet Tuesday at 10am")
            eval_result = verify_meeting_negotiated(result)
            assert eval_result.passed is False
            assert "Alice" in eval_result.details

        def test_invalid_thursday_meeting(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_meeting_negotiated
            result = make_task_result(agent_answer="Thursday 2pm is confirmed")
            eval_result = verify_meeting_negotiated(result)
            assert eval_result.passed is False
            assert "Bob" in eval_result.details

        def test_no_time_mentioned(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_meeting_negotiated
            result = make_task_result(agent_answer="I sent Bob an email about the meeting.")
            eval_result = verify_meeting_negotiated(result)
            assert eval_result.passed is False

        def test_empty_answer(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_meeting_negotiated
            result = make_task_result()
            eval_result = verify_meeting_negotiated(result)
            assert eval_result.passed is False

    class TestVerify3WayMeeting:
        """Tests for 3-way meeting negotiation verification."""

        def test_valid_wednesday_morning(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_3way_meeting
            result = make_task_result(
                agent_answer="[alice]: Wednesday 11am works for me\n[bob]: Wednesday 11am confirmed\n[charlie]: See you Wednesday at 11am!"
            )
            eval_result = verify_3way_meeting(result)
            assert eval_result.passed is True
            assert "Wednesday" in eval_result.details

        def test_valid_monday_afternoon(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_3way_meeting
            result = make_task_result(
                agent_answer="Meeting confirmed for Monday at 3pm. All three of us will attend."
            )
            eval_result = verify_3way_meeting(result)
            assert eval_result.passed is True

        def test_invalid_tuesday_meeting(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_3way_meeting
            result = make_task_result(agent_answer="Let's all meet Tuesday at 3pm")
            eval_result = verify_3way_meeting(result)
            assert eval_result.passed is False
            assert "Alice" in eval_result.details

        def test_invalid_thursday_meeting(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_3way_meeting
            result = make_task_result(agent_answer="Thursday 2pm works for the three of us")
            eval_result = verify_3way_meeting(result)
            assert eval_result.passed is False

        def test_invalid_friday_afternoon(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_3way_meeting
            result = make_task_result(agent_answer="Friday at 2pm confirmed for all")
            eval_result = verify_3way_meeting(result)
            assert eval_result.passed is False

        def test_no_time_mentioned(self):
            from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_3way_meeting
            result = make_task_result(
                agent_answer="We're still trying to find a time that works for everyone."
            )
            eval_result = verify_3way_meeting(result)
            assert eval_result.passed is False


class TestIMAPVerification:
    """Tests for IMAP-based email verification."""

    @pytest.fixture
    def mock_imap(self):
        """Mock IMAP functions."""
        import unittest.mock as mock
        with mock.patch("pet_to_wild.universes.startup.custom_evaluators.coordination_checker.search_emails") as m:
            yield m

    def test_imap_both_emails_found(self, mock_imap):
        """Should pass when both Alice→Bob and Bob→Alice emails found."""
        from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import _verify_emails_exchanged_imap
        mock_imap.return_value = [1]  # Return list with one UID

        success, details, contents = _verify_emails_exchanged_imap(include_content=False)
        assert success is True
        assert "Alice→Bob" in details[0]
        assert "Bob→Alice" in details[1]
        assert "✓" in details[0]
        assert "✓" in details[1]

    def test_imap_alice_email_missing(self, mock_imap):
        """Should fail when Alice→Bob email not found."""
        from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import _verify_emails_exchanged_imap
        # First call is checking Bob's inbox for Alice's email
        # Second call is checking Alice's inbox for Bob's email
        mock_imap.side_effect = [[], [1]]

        success, details, contents = _verify_emails_exchanged_imap(include_content=False)
        assert success is False
        assert "✗" in details[0]  # Alice→Bob failed
        assert "✓" in details[1]  # Bob→Alice passed

    def test_imap_bob_email_missing(self, mock_imap):
        """Should fail when Bob→Alice email not found."""
        from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import _verify_emails_exchanged_imap
        mock_imap.side_effect = [[1], []]

        success, details, contents = _verify_emails_exchanged_imap(include_content=False)
        assert success is False
        assert "✓" in details[0]  # Alice→Bob passed
        assert "✗" in details[1]  # Bob→Alice failed

    def test_imap_both_emails_missing(self, mock_imap):
        """Should fail when both emails missing."""
        from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import _verify_emails_exchanged_imap
        mock_imap.return_value = []

        success, details, contents = _verify_emails_exchanged_imap(include_content=False)
        assert success is False
        assert "✗" in details[0]
        assert "✗" in details[1]

    def test_imap_error_handling(self, mock_imap):
        """Should handle IMAP errors gracefully."""
        from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import _verify_emails_exchanged_imap
        mock_imap.side_effect = Exception("Connection refused")

        success, details, contents = _verify_emails_exchanged_imap(include_content=False)
        assert success is False
        assert "Failed" in details[0]

    def test_verify_meeting_with_imap_no_emails(self, mock_imap):
        """Should fail when no emails were exchanged."""
        from pet_to_wild.universes.startup.custom_evaluators.coordination_checker import verify_meeting_negotiated_with_imap
        mock_imap.return_value = []

        result = make_task_result(agent_answer="No meeting scheduled")

        eval_result = verify_meeting_negotiated_with_imap(result, show_emails=False)
        assert eval_result.passed is False
        assert "Emails were not exchanged" in eval_result.details


class TestEvalResultFormat:
    """Tests to ensure EvalResult format is consistent."""

    def test_all_evaluators_return_eval_result(self):
        """All evaluators should return EvalResult with correct type."""
        result = make_task_result(agent_answer="test", page_content="test")

        evaluators = [
            check_inbox_loaded,
            check_sent_folder,
            check_email_composed,
            check_login_error_recovery,
            check_focalboard_logged_in,
            check_gitea_logged_in,
            check_kanban_card_created,
            check_gitea_issue_created,
            check_pr_created,
            check_repo_forked,
        ]

        for evaluator in evaluators:
            eval_result = evaluator(result)
            assert isinstance(eval_result, EvalResult), f"{evaluator.__name__} should return EvalResult"
            assert eval_result.eval_type == EvalType.CUSTOM_FUNCTION
            assert isinstance(eval_result.passed, bool)
            assert isinstance(eval_result.details, str)

    def test_details_always_provided(self):
        """All evaluators should provide meaningful details."""
        result = make_task_result()

        evaluators = [
            check_inbox_loaded,
            check_sent_folder,
            check_email_composed,
            check_login_error_recovery,
            check_focalboard_logged_in,
            check_gitea_logged_in,
            check_kanban_card_created,
            check_gitea_issue_created,
            check_pr_created,
            check_repo_forked,
        ]

        for evaluator in evaluators:
            eval_result = evaluator(result)
            assert len(eval_result.details) > 0, f"{evaluator.__name__} should provide details"
