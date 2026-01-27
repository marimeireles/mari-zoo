# Proposal: Benchmark CLI Redesign (v2)

**Status:** Draft
**Author:** Claude
**Date:** 2026-01-26
**Revised:** Based on review feedback

## Problem Statement

The current benchmark CLI has several usability issues:

1. **Overloaded `--model` flag**: For `browser_use`, expects `google/gemini-2.5-flash-lite`. For `claude_sdk`, internally maps from `sonnet`/`haiku`/`opus`. Confusing and error-prone.

2. **Invalid combinations possible**: Users can specify `--harness claude_sdk --model google/gemini-2.5-flash-lite` which fails at runtime.

3. **Cartesian product problem**: Current design creates all combinations of `models × harnesses`, including invalid ones.

4. **No validation**: Invalid configurations fail at runtime, not upfront.

5. **No reproducibility**: CLI invocations hard to version control.

## Goals

- Simple commands for common scenarios (1-2 flags)
- Validate configurations before running
- Reproducible research workflows via config files
- Backwards compatible with existing CLI
- Support resume for long-running benchmarks

## Non-Goals

- Changing benchmark execution engine
- Parallel execution (future work)
- Cost estimation (future work)

---

## Proposed Design

### Two-tier approach (simplified from v1)

```
┌─────────────────────────────────────────────────────────────┐
│  Tier 1: Presets + CLI (simple & flexible)                  │
│  uv run zoo-eval benchmark startup -t email --preset quick  │
│  uv run zoo-eval benchmark startup -t email --spec browser_use:gpt-4o │
├─────────────────────────────────────────────────────────────┤
│  Tier 2: Config files (reproducible research)               │
│  uv run zoo-eval benchmark --config-file study.yaml         │
└─────────────────────────────────────────────────────────────┘
```

### Data Model Change

**Current `BenchmarkConfig`:**
```python
@dataclass
class BenchmarkConfig:
    models: list[str]           # Creates Cartesian product
    harnesses: list[str]        # with this
```

**New `BenchmarkConfig`:**
```python
@dataclass
class HarnessModelSpec:
    """Explicit harness + model pairing."""
    harness: str
    model: str
    name: str | None = None  # Optional display name

@dataclass
class BenchmarkConfig:
    # New field for explicit pairings
    specs: list[HarnessModelSpec] = field(default_factory=list)

    # OLD fields kept for backwards compatibility (deprecated)
    models: list[str] = field(default_factory=list)
    harnesses: list[str] = field(default_factory=list)

    def get_configurations(self) -> list[HarnessModelSpec]:
        """Return specs, or generate from legacy fields."""
        if self.specs:
            return self.specs
        # Legacy fallback: Cartesian product (with validation)
        return [
            HarnessModelSpec(harness=h, model=m)
            for h in self.harnesses
            for m in self.models
            if self._is_valid_pair(h, m)
        ]
```

### Tier 1: Presets + Explicit Specs

**Two built-in presets** (start simple, add more later):

```bash
# Quick smoke test - single fast configuration
uv run zoo-eval benchmark startup -t email -i 101 --preset quick

# Standard comparison - browser_use vs claude_sdk
uv run zoo-eval benchmark startup -t email -i 101 --preset compare
```

**Preset definitions** (embedded in Python, not YAML file):

```python
# src/zoo_eval/benchmark_presets.py

PRESETS = {
    "quick": {
        "description": "Fast smoke test with single configuration",
        "specs": [
            {"harness": "browser_use", "model": "google/gemini-2.5-flash-lite"},
        ],
        "trials": 1,
        "levels": ["L1"],
    },
    "compare": {
        "description": "Compare browser_use vs claude_sdk",
        "specs": [
            {"harness": "browser_use", "model": "google/gemini-2.5-flash-lite"},
            {"harness": "claude_sdk", "model": "sonnet"},
        ],
        "trials": 3,
        "levels": ["L1"],
    },
}
```

**Explicit `--spec` flag** (not `--config` to avoid ambiguity):

```bash
# Single spec
uv run zoo-eval benchmark startup -t email \
  --spec "browser_use:google/gemini-2.5-flash-lite"

# Multiple specs
uv run zoo-eval benchmark startup -t email \
  --spec "browser_use:google/gemini-2.5-flash-lite" \
  --spec "browser_use:openai/gpt-4o" \
  --spec "claude_sdk:sonnet"
```

**Preset + overrides:**

```bash
# Use preset but override trials
uv run zoo-eval benchmark startup -t email --preset quick --trials 5

# Use preset but add another spec
uv run zoo-eval benchmark startup -t email --preset compare \
  --spec "claude_sdk:opus"
```

### Precedence Rules

Clear, documented precedence (highest to lowest):

1. **CLI flags** (`--trials 5`) override everything
2. **`--spec` flags** add to preset specs (don't replace)
3. **`--preset` defaults**
4. **Hardcoded defaults** (trials=1, levels=[L1])

Example:
```bash
--preset compare --spec "claude_sdk:opus" --trials 5
```
Results in:
- specs: [browser_use:gemini-flash, claude_sdk:sonnet, claude_sdk:opus]
- trials: 5 (CLI override)
- levels: [L1] (from preset)

### Tier 2: Config Files

**Separate `--config-file` flag** (not `--config`):

```bash
uv run zoo-eval benchmark --config-file experiments/study.yaml
```

**Simplified config format:**

```yaml
# experiments/study.yaml
name: "Harness Comparison Study"

universe: pet_to_wild/universes/startup
tasks:
  - file: email
    ids: [101, 102, 103]

specs:
  - harness: browser_use
    model: google/gemini-2.5-flash-lite
    name: "Gemini Flash"  # Optional display name

  - harness: browser_use
    model: openai/gpt-4o
    name: "GPT-4o"

  - harness: claude_sdk
    model: sonnet
    name: "Claude Sonnet"

trials: 5
levels: [L1, L2]
timeout: 120
headless: true
```

**Config file + CLI overrides:**

```bash
# Run config but with fewer trials for testing
uv run zoo-eval benchmark --config-file study.yaml --trials 1
```

### Validation

**Upfront validation before running:**

```python
# src/zoo_eval/benchmark_config.py

VALID_MODELS = {
    "browser_use": {
        # Format: provider/model-name
        "pattern": r"^[\w-]+/[\w.-]+$",
        "examples": ["google/gemini-2.5-flash-lite", "openai/gpt-4o"],
    },
    "claude_sdk": {
        # Format: tier name only
        "valid": {"haiku", "sonnet", "opus"},
    },
}

def validate_spec(spec: HarnessModelSpec) -> list[str]:
    """Return list of errors, empty if valid."""
    errors = []

    if spec.harness not in VALID_MODELS:
        errors.append(f"Unknown harness: {spec.harness}")
        return errors

    rules = VALID_MODELS[spec.harness]

    if "valid" in rules:
        if spec.model not in rules["valid"]:
            errors.append(
                f"{spec.harness} requires model in {rules['valid']}, "
                f"got '{spec.model}'"
            )
    elif "pattern" in rules:
        if not re.match(rules["pattern"], spec.model):
            errors.append(
                f"{spec.harness} requires model format like "
                f"{rules['examples'][0]}, got '{spec.model}'"
            )

    return errors
```

**Validation modes:**

```bash
# Validate only, don't run
uv run zoo-eval benchmark startup -t email --preset compare --validate

# Dry run - show what would run
uv run zoo-eval benchmark startup -t email --preset compare --dry-run
```

### Resume Support

Add `--resume` flag for long benchmarks:

```bash
# First run (crashes partway through)
uv run zoo-eval benchmark startup -t email --preset compare --trials 10 \
  --output results.json

# Resume from where it left off
uv run zoo-eval benchmark startup -t email --preset compare --trials 10 \
  --output results.json --resume
```

**Implementation:** Check output JSON for completed (task_id, spec, trial) tuples and skip them.

### CLI Help

```
$ uv run zoo-eval benchmark --help

Usage: zoo-eval benchmark [OPTIONS] [UNIVERSE]

Run benchmarks comparing models and harnesses.

QUICK START:
  # Smoke test with fast model
  zoo-eval benchmark startup -t email --preset quick

  # Compare browser_use vs claude_sdk
  zoo-eval benchmark startup -t email --preset compare

  # Custom configuration
  zoo-eval benchmark startup -t email --spec "browser_use:gpt-4o" --trials 3

  # Reproducible research
  zoo-eval benchmark --config-file study.yaml

PRESETS:
  quick     Single fast configuration (1 trial)
  compare   browser_use vs claude_sdk (3 trials)

OPTIONS:
  --preset NAME           Use built-in preset
  --spec HARNESS:MODEL    Add harness:model configuration (repeatable)
  --config-file FILE      Load configuration from YAML file

  -t, --task FILE         Task file(s) to include
  -i, --id ID             Specific task IDs
  -n, --trials INT        Trials per configuration [default: 1]
  -L, --level LEVEL       Autonomy levels [default: L1]

  -o, --output FILE       Output JSON file
  --resume                Resume incomplete benchmark from output file
  --validate              Validate configuration without running
  --dry-run               Show what would run without executing
  --list-presets          Show available presets with descriptions
```

---

## Migration & Backwards Compatibility

### JSON Output Versioning

Add schema version to output:

```json
{
  "schema_version": 2,
  "config": {
    "specs": [...],
    "models": [],
    "harnesses": []
  }
}
```

Reader code handles both:

```python
def load_benchmark_results(path: Path) -> BenchmarkResults:
    data = json.loads(path.read_text())
    version = data.get("schema_version", 1)

    if version == 1:
        # Legacy format: models + harnesses lists
        return _load_v1(data)
    else:
        # New format: specs list
        return _load_v2(data)
```

### CLI Backwards Compatibility

Old syntax still works but shows deprecation warning:

```bash
# Old syntax (deprecated, still works)
uv run zoo-eval benchmark startup -t email \
  --harness browser_use --model google/gemini-2.5-flash-lite

# Warning: --harness/--model flags are deprecated.
# Use --spec "browser_use:google/gemini-2.5-flash-lite" instead.
```

### Migration Timeline

- **v1.x:** New flags added, old flags deprecated with warning
- **v2.0:** Old flags removed (major version bump)

---

## Implementation Plan

### Phase 1: Validation (4-6 hours)
- Add `validate_spec()` function
- Add `--validate` and `--dry-run` flags
- No breaking changes, pure addition

### Phase 2: Specs + Presets (6-8 hours)
- Add `HarnessModelSpec` dataclass
- Add `specs` field to `BenchmarkConfig`
- Implement `--spec` and `--preset` flags
- Add 2 presets (quick, compare)
- Deprecation warnings for old flags

### Phase 3: Config Files (4-6 hours)
- Add `--config-file` flag
- YAML parsing with validation
- Precedence handling (config + CLI overrides)

### Phase 4: Resume Support (4-6 hours)
- Add `--resume` flag
- Check output file for completed runs
- Skip already-completed configurations

### Phase 5: Cleanup (2-4 hours)
- Documentation updates
- Test coverage
- Help text refinement

**Total estimate: 20-30 hours**

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/zoo_eval/benchmark.py` | Add `HarnessModelSpec`, update `BenchmarkConfig`, add validation |
| `src/zoo_eval/cli.py` | Add `--spec`, `--preset`, `--config-file`, `--validate`, `--dry-run`, `--resume` |
| `src/zoo_eval/benchmark_presets.py` | New file with preset definitions |
| `src/zoo_eval/benchmark_config.py` | New file with validation logic |
| `tests/test_benchmark.py` | Tests for new functionality |

---

## Open Questions

1. **Should `--spec` support short aliases?** E.g., `--spec bu:gpt-4o` → `browser_use:openai/gpt-4o`

2. **Should presets be user-extensible?** Via `~/.zoo-eval/presets.yaml`? (Recommend: No, keep simple for v1)

3. **Should `--dry-run` show cost estimates?** (Recommend: Future work, not v1)

---

## Success Metrics

- Common scenarios achievable in <40 characters
- Zero runtime errors from invalid harness+model combinations
- Config files used for published benchmarks
- `--resume` successfully recovers from crashes

---

## Appendix: Example Sessions

### Quick smoke test
```bash
$ uv run zoo-eval benchmark startup -t email -i 101 --preset quick
Validating configuration...
  ✓ browser_use:google/gemini-2.5-flash-lite

Running benchmark: 1 task × 1 config × 1 trial = 1 run
[1/1] Task 101, browser_use:gemini-flash, trial 1
  → PASS (28.5s, 6 steps)

Results: 1 passed, 0 failed (100.0%)
```

### Compare harnesses
```bash
$ uv run zoo-eval benchmark startup -t email -i 101,102 --preset compare
Validating configuration...
  ✓ browser_use:google/gemini-2.5-flash-lite
  ✓ claude_sdk:sonnet

Running benchmark: 2 tasks × 2 configs × 3 trials = 12 runs
[1/12] Task 101, browser_use:gemini-flash, trial 1...
```

### Custom with validation error
```bash
$ uv run zoo-eval benchmark startup -t email --spec "claude_sdk:gpt-4o"
Validation error:
  claude_sdk requires model in {haiku, sonnet, opus}, got 'gpt-4o'

Did you mean: --spec "browser_use:openai/gpt-4o"
            or: --spec "claude_sdk:sonnet"
```

### Resume after crash
```bash
$ uv run zoo-eval benchmark startup -t email --preset compare --trials 10 \
    --output results.json --resume
Loading existing results from results.json...
  Found 7 completed runs, resuming from run 8

[8/20] Task 102, claude_sdk:sonnet, trial 2...
```
