# Custom Evaluators

This directory contains user-defined evaluation functions for benchmark tasks.

## Quick Start

1. **Create your function** in a new file (e.g., `my_checker.py`)
2. **Export it** in `__init__.py`
3. **Reference it** in your task YAML config

## Example

```python
# custom_evaluators/my_checker.py
from zoo_eval.evaluators import EvalResult
from zoo_eval.models import EvalType, TaskResult

def my_custom_check(result: TaskResult) -> EvalResult:
    if "success" in result.page_content.lower():
        return EvalResult(
            passed=True,
            eval_type=EvalType.CUSTOM_FUNCTION,
            details="Found success indicator"
        )
    return EvalResult(
        passed=False,
        eval_type=EvalType.CUSTOM_FUNCTION,
        details="Success indicator not found"
    )
```

Then in your task config:

```yaml
eval:
  types:
    - custom_function
  custom_function: "custom_evaluators.my_custom_check"
```

## Available Functions

- **`check_email_from_diana`**: Verifies an email from diana@snappymail.zoo about Q4 budget is visible on the page

## Documentation

See [../docs/CUSTOM_EVALUATORS.md](../docs/CUSTOM_EVALUATORS.md) for complete API documentation and examples.
