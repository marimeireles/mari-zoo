# Authoring Scenes

Scenes define environment setup and runtime behavior for tasks. This guide covers how to write scene YAML files using the declarative action API.

## Directory Structure

```
universes/<universe>/
├── scenes/
│   └── my_scene.yaml
├── fixtures/
│   └── my_scene/           # Scene-specific content files
│       ├── code.py
│       └── readme.md
└── scripts/                # Only for complex custom logic
```

## Scene Structure

```yaml
name: my_scene
description: "What this scene does"

setup:      # Runs before task starts
  - type: email
    ...

actions:    # Runs during task (with triggers)
  - trigger: { type: time, delay: 5 }
    type: email
    ...

agents:     # Agent spawn triggers
  - trigger: { type: request, url_contains: "/pulls" }
    name: bob
```

## Action Types

### email

Send an email. Credentials resolved from `credentials/snappymail.zoo.yaml`.

```yaml
- type: email
  from: bob              # Agent name (looked up in credentials)
  to: alice@snappymail.zoo
  subject: Hello
  body: |
    Email body here...
```

Or load body from fixture:

```yaml
- type: email
  from: bob
  to: alice@snappymail.zoo
  subject: Hello
  body_file: fixtures/my_scene/email_body.txt
```

### gitea.repo

Create a Gitea repository.

```yaml
- type: gitea.repo
  owner: bob             # Agent name
  name: my-repo
  description: Optional description
  private: false         # Optional, default false
  auto_init: true        # Optional, default true
```

### gitea.file

Add a file to a repository.

```yaml
- type: gitea.file
  owner: bob
  repo: my-repo
  path: src/main.py
  content: |
    print("hello")
```

Or load from fixture:

```yaml
- type: gitea.file
  owner: bob
  repo: my-repo
  path: src/main.py
  content_file: fixtures/my_scene/main.py
```

### gitea.issue

Create an issue.

```yaml
- type: gitea.issue
  owner: bob
  repo: my-repo
  title: "[BUG] Something is broken"
  body: |
    Description of the issue...
```

### focalboard.board

Create a Kanban board.

```yaml
- type: focalboard.board
  user: diana            # Agent name
  title: Sprint 1
```

### focalboard.card

Create a card on the most recently created board.

```yaml
- type: focalboard.card
  user: diana
  title: Fix the bug
  description: Priority HIGH
```

Or specify board explicitly:

```yaml
- type: focalboard.card
  user: diana
  board: <board-id>      # From previous board creation
  title: Fix the bug
```

### postmill.comment

Create a comment on a Postmill submission.

```yaml
- type: postmill.comment
  user: MarvelsGrantMan136
  submission_id: 123
  body: |
    My comment here...
```

### script

Run a Python script for logic that can't be expressed declaratively.

```yaml
- type: script
  script_path: scripts/my_script.py
```

See [Scripts Directory](#scripts-directory) below for when to use scripts vs declarative actions.

## Scripts Directory

The `scripts/` directory is for **complex logic that can't be expressed declaratively** in YAML. This is similar to how `custom_evaluators/` handles custom evaluation logic.

### When to Use Scripts

Use scripts when you need:
- **Dynamic lookups** - Finding resources by searching (e.g., find issue by title)
- **Conditional logic** - Different behavior based on runtime state
- **Loops with side effects** - Posting multiple comments to a dynamically-found target
- **External API calls** - Fetching data from outside the Zoo

### When NOT to Use Scripts

Prefer declarative YAML actions when:
- Sending emails with known recipients
- Creating repos, files, issues with fixed content
- Creating boards and cards
- Any action where all parameters are known at authoring time

### Script Structure

Scripts should:
1. Load data from `fixtures/` (not embed data inline)
2. Use `get_credential()` from `zoo_eval.auth` (not hardcode passwords)
3. Contain only logic, not data

```python
#!/usr/bin/env python3
"""Description of what this script does."""

from pathlib import Path
import yaml

from zoo_eval.auth import get_credential
from zoo_eval.zoo_cli import gitea_create_comment, gitea_list_issues


def load_data() -> list[str]:
    """Load data from fixture file."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "my_scene" / "data.yaml"
    with open(fixture_path) as f:
        return yaml.safe_load(f)["items"]


def main():
    cred = get_credential("gitea", "bob")
    data = load_data()

    # Dynamic logic here...


if __name__ == "__main__":
    main()
```

### Examples

**Dynamic issue lookup + multiple comments:**
```
scripts/trigger_spam_comments.py  # Logic: find issue, loop
fixtures/issue_spam_attack/spam_comments.yaml  # Data: comment bodies
```

**Dynamic post lookup + multiple replies:**
```
scripts/seed_vacuum_replies.py  # Logic: find latest post, loop
fixtures/vacuum_shopping/replies.yaml  # Data: reply bodies
```

## Fixtures

Store large content (code files, long emails) in the fixtures directory:

```
fixtures/
└── pr_feedback/
    ├── utils.py
    └── README.md
```

Reference with `*_file` fields:

```yaml
- type: gitea.file
  content_file: fixtures/pr_feedback/utils.py

- type: email
  body_file: fixtures/pr_feedback/email_template.txt
```

## Credentials

Credentials are automatically resolved from `credentials/*.zoo.yaml` files using the agent name.

When you write `owner: bob` in a gitea action, the system looks up the agent named "bob" in `credentials/gitea.zoo.yaml` and uses their credentials.

### Credential Files

Located in `credentials/` at the repo root:

```
credentials/
├── snappymail.zoo.yaml   # Email accounts
├── gitea.zoo.yaml        # Git hosting
├── focalboard.zoo.yaml   # Kanban boards
├── postmill.zoo.yaml     # Reddit-like forum
└── ...
```

Example `credentials/gitea.zoo.yaml`:

```yaml
site: gitea.zoo
users:
  - username: bob
    password: bob123
    agent: bob           # This is what you reference in scenes
  - username: alice
    password: alice123
    agent: alice
```

### Adding New Users

To add a new user for use in scenes:

1. **Add to credential file**: Edit the relevant `credentials/*.zoo.yaml` file

   ```yaml
   # credentials/snappymail.zoo.yaml
   users:
     # ... existing users ...
     - username: newuser@snappymail.zoo
       password: newuser123
       agent: newuser      # Use this in scenes: from: newuser
   ```

2. **Create user in Zoo**: The user must exist in the Zoo service. Users are created at Zoo startup from seed data. To add permanently, update the Zoo's user provisioning.

3. **Use in scenes**:
   ```yaml
   - type: email
     from: newuser        # Matches agent: newuser
     to: bob@snappymail.zoo
     ...
   ```

### Programmatic Access

For custom scripts that still need credentials:

```python
from zoo_eval.auth import get_credential

cred = get_credential("gitea", "bob")
print(cred.username)  # "bob"
print(cred.password)  # "bob123"
```

## Triggers

Actions in the `actions:` section require triggers:

```yaml
actions:
  - trigger:
      type: time
      delay: 30          # Seconds
    type: email
    ...

  - trigger:
      type: request
      url_contains: "/pulls"
      method: POST
    type: email
    ...

  - trigger:
      type: poll
      poll_endpoint: "https://gitea.zoo/api/v1/repos/bob/test"
      poll_contains: "issue"
      timeout: 300
    type: email
    ...
```

## Complete Example

```yaml
name: code_review
description: "Sets up repo, sends feedback after PR"

setup:
  - type: gitea.repo
    owner: bob
    name: my-project

  - type: gitea.file
    owner: bob
    repo: my-project
    path: main.py
    content_file: fixtures/code_review/main.py

  - type: gitea.issue
    owner: bob
    repo: my-project
    title: "Add error handling"
    body: |
      We need better error handling in main.py

actions:
  - trigger:
      type: request
      url_contains: "/pulls"
      method: POST
    type: email
    from: bob
    to: alice@snappymail.zoo
    subject: "PR feedback"
    body: |
      Thanks for the PR! A few suggestions...

agents:
  - trigger:
      type: request
      url_contains: "/pulls"
    name: bob
```
