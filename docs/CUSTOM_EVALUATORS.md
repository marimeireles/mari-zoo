# Custom Evaluation Functions

Custom evaluation functions allow you to write Python code to verify task completion in ways that go beyond the built-in evaluators (string_match, url_match, etc.).

## When to Use Custom Functions

Use custom functions when you need to:
- Parse and inspect HTML elements on the page
- Perform complex validation logic
- Check for specific UI states or interactions
- Verify data structures in page content
- Implement domain-specific verification rules

## API

### Function Signature

```python
from zoo_eval.models import TaskResult
from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType

def my_custom_evaluator(result: TaskResult) -> EvalResult:
    """
    Args:
        result: TaskResult containing:
            - page_content (str | None): Final page HTML
            - agent_answer (str | None): Agent's final response
            - final_url (str | None): Final page URL
            - success (bool): Whether agent execution succeeded
            - agent_results (list): Individual agent results
            - steps (int): Number of steps taken
            - duration_seconds (float): Execution time

    Returns:
        EvalResult with:
            - passed (bool): Whether evaluation passed
            - eval_type (EvalType): Should be EvalType.CUSTOM_FUNCTION
            - details (str): Explanation of pass/fail
    """
    # Your verification logic here

    if verification_passed:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="Detailed explanation of what was verified"
        )
    else:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="Explanation of what failed"
        )
```

### Available Data

The `TaskResult` object provides:

- **`page_content`**: Full HTML of the final page (useful for parsing)
- **`agent_answer`**: The agent's final text response
- **`final_url`**: URL the agent ended on
- **`agent_results`**: List of individual agent results (for multi-agent tasks)
- **`success`**: Whether the agent completed without errors
- **`error`**: Error message if agent failed
- **`steps`**: Number of actions taken
- **`duration_seconds`**: How long execution took

## Creating Custom Functions

### 1. Create Your Function

Place custom functions in the `custom_evaluators/` directory:

```bash
# Create a new module for your custom functions
touch custom_evaluators/my_checks.py
```

### 2. Write the Function

```python
# custom_evaluators/my_checks.py
from bs4 import BeautifulSoup
from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType, TaskResult


def check_specific_element(result: TaskResult) -> EvalResult:
    """Check if a specific element exists on the page."""
    if not result.page_content:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="No page content available",
        )

    soup = BeautifulSoup(result.page_content, "html.parser")

    # Look for a specific element
    target_element = soup.find("div", {"class": "success-message"})

    if target_element and "Operation completed" in target_element.text:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="Found success message with expected text",
        )
    else:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="Success message not found or incorrect text",
        )
```

### 3. Export in __init__.py

```python
# custom_evaluators/__init__.py
from .my_checks import check_specific_element

__all__ = ["check_specific_element"]
```

### 4. Reference in Task Config

```yaml
# In your task YAML file
eval:
  types:
    - custom_function
  custom_function: "custom_evaluators.check_specific_element"
```

## Example: Email Verification

Here's a complete example that checks for an email from a specific sender:

```python
# custom_evaluators/email_checker.py
from bs4 import BeautifulSoup
from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType, TaskResult


def check_email_from_diana(result: TaskResult) -> EvalResult:
    """Verify an email from diana@snappymail.zoo is visible."""
    if not result.page_content:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="No page content captured",
        )

    soup = BeautifulSoup(result.page_content, "html.parser")
    page_text = soup.get_text().lower()

    # Check for sender
    if "diana@snappymail.zoo" not in page_text:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="No email from diana@snappymail.zoo found",
        )

    # Check for subject keywords
    if "q4" in page_text and "budget" in page_text:
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="Found email from Diana about Q4 budget",
        )
    else:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="Email found but missing Q4 budget keywords",
        )
```

Task configuration:

```yaml
- id: 101
  sites:
    - mail
  intent: "Check your inbox and tell me who sent you an email about the Q4 budget"
  start_url: "https://snappymail.zoo"
  require_login: true
  username: alice@snappymail.zoo
  password: alice123

  eval:
    types:
      - custom_function
    custom_function: "custom_evaluators.check_email_from_diana"
```

## Common Patterns

### Pattern 1: HTML Element Inspection

```python
def check_button_exists(result: TaskResult) -> EvalResult:
    soup = BeautifulSoup(result.page_content, "html.parser")
    button = soup.find("button", {"id": "submit-button"})

    return EvalResult(
        passed=button is not None,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Submit button {'found' if button else 'not found'}",
    )
```

### Pattern 2: Text Content Verification

```python
def check_confirmation_text(result: TaskResult) -> EvalResult:
    if not result.agent_answer:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="No agent answer provided",
        )

    expected_phrases = ["order confirmed", "confirmation number"]
    found = [p for p in expected_phrases if p in result.agent_answer.lower()]

    return EvalResult(
        passed=len(found) == len(expected_phrases),
        eval_type=EvalType.CUSTOM_FUNCTION,
        details=f"Found {len(found)}/{len(expected_phrases)} expected phrases",
    )
```

### Pattern 3: URL and Content Combination

```python
def check_success_page(result: TaskResult) -> EvalResult:
    # Check URL
    if not result.final_url or "/success" not in result.final_url:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details=f"Not on success page, URL: {result.final_url}",
        )

    # Check page content
    if "Transaction completed" not in result.page_content:
        return EvalResult(
            passed=False,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="On success page but missing confirmation message",
        )

    return EvalResult(
        passed=True,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details="Successfully verified completion page and message",
    )
```

## Best Practices

1. **Always check for None**: `page_content`, `agent_answer`, and `final_url` can be None
2. **Provide detailed feedback**: The `details` field should explain what was checked and why it passed/failed
3. **Handle errors gracefully**: Wrap parsing logic in try/except blocks
4. **Keep functions focused**: One function should verify one specific thing
5. **Use descriptive names**: Function names should clearly indicate what they verify
6. **Document your functions**: Include docstrings explaining the verification logic

## Combining with Other Evaluators

You can use custom functions alongside other evaluation types:

```yaml
eval:
  types:
    - custom_function  # Check page structure
    - string_match     # Check agent response text

  custom_function: "custom_evaluators.check_email_from_diana"

  answers:
    must_include:
      - diana
```

Both evaluations must pass for the task to be considered successful.

## Dependencies

Custom functions can use any Python libraries available in the environment:
- `beautifulsoup4` for HTML parsing (already installed)
- `lxml` for XML/HTML processing
- Any other libraries you install in the zoo-eval environment

## Debugging

If your custom function isn't working:

1. **Check import path**: Ensure the module path is correct
2. **Verify function name**: Must match exactly (case-sensitive)
3. **Check return type**: Must return `EvalResult`
4. **Examine error details**: The evaluator will report import/execution errors
5. **Test locally**: Import and call your function directly to debug

Example debugging:

```python
from zoo_eval.models import TaskResult
from custom_evaluators import check_email_from_diana

# Create mock result for testing
mock_result = TaskResult(
    task_id=101,
    success=True,
    page_content="<html>Email from diana@snappymail.zoo about Q4 budget</html>",
    agent_answer="Diana sent the email",
)

# Test your function
result = check_email_from_diana(mock_result)
print(f"Passed: {result.passed}")
print(f"Details: {result.details}")
```

## Architecture

```
zoo-eval/
├── custom_evaluators/          # Your custom functions
│   ├── __init__.py            # Export functions here
│   ├── email_checker.py       # Example: email verification
│   └── my_checks.py           # Your custom checks
├── src/zoo_eval/
│   ├── evaluators.py          # Built-in evaluators + CustomFunctionEvaluator
│   └── models.py              # EvalType, TaskResult, etc.
└── configs/
    └── my_tasks.yaml          # Reference custom functions here
```

When a task runs:
1. Task config specifies `custom_function: "custom_evaluators.my_function"`
2. `CustomFunctionEvaluator` dynamically imports the module
3. It calls your function with the `TaskResult`
4. Your function returns an `EvalResult`
5. The result is included in the final evaluation report
