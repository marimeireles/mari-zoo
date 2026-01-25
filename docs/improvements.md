# Zoo-Eval Improvements Tracker

This document tracks identified improvements and technical debt in the zoo-eval project.

**Created:** 2026-01-24
**Last Updated:** 2026-01-24
**Validated:** Yes (subagent review completed)

---

## PR Group 1: Critical Runtime Fixes
**Priority:** MUST DO FIRST
**Estimated Time:** 30 minutes
**Can be done together in single PR**

### 1. `security_checks` Reference Crash
- **File:** `src/zoo_eval/evaluators.py:383-386`
- **Issue:** References `evaluation.security_checks` but `SecurityCheck` class doesn't exist in `models.py`
- **Impact:** `HumanCriticEvaluator` crashes at runtime with `AttributeError`
- **Fix:** Remove the security_checks block entirely:
  ```python
  # DELETE these lines (383-386):
  "security_checks": [
      {"type": sc.check_type, "params": sc.params}
      for sc in evaluation.security_checks
  ],
  ```
- **Complexity:** Trivial
- **Status:** [ ] Not started

### 2. LLM Model Should Be Configurable
- **File:** `src/zoo_eval/evaluators.py:310`
- **Issue:** Model is hardcoded, should be configurable via environment variable
- **Fix:** Change to:
  ```python
  model=os.environ.get("OPENAI_JUDGE_MODEL", "gpt-5"),
  ```
- **Complexity:** Trivial
- **Status:** [ ] Not started

### 3. Task 105 Wrong Password
- **File:** `pet_to_wild/universes/startup/tasks/email.yaml:132`
- **Issue:** Password is `alice` instead of `alice123` (inconsistent with other tasks)
- **Fix:** Change `password: alice` to `password: alice123`
- **Complexity:** Trivial
- **Status:** [ ] Not started

### 4. Task 104 Instruction Error
- **File:** `pet_to_wild/universes/startup/tasks/email.yaml:105`
- **Issue:** Alice is the sender but L1 says "send an email to Alice, Bob, and Charlie"
- **Fix:** Change to "send an email to Diana, Bob, and Charlie"
- **Also fix:** Line 112 eval criteria references wrong recipients
- **Complexity:** Trivial
- **Status:** [ ] Not started

---

## PR Group 2: CLI Autonomy Level Control
**Priority:** High (critical for usability)
**Estimated Time:** 2 hours
**Blocks efficient benchmarking**

### 5. Add `--level` CLI Flag
- **Files to modify:**
  - `src/zoo_eval/cli.py` - Add `--level/-L` option
  - `src/zoo_eval/runner.py` - Pass levels through
  - `src/zoo_eval/multi_agent_runner.py:432` - Use passed levels
- **Issue:** Always runs L0, L1, L2 regardless of user intent. Triples execution time.
- **Current code:**
  ```python
  for autonomy_level in ["L0", "L1", "L2"]:  # HARDCODED
  ```
- **Fix:**
  1. Add CLI option: `--level/-L` (can be specified multiple times)
  2. Default to `["L1"]` if not specified
  3. Thread selected levels through `RunConfig` to runner
- **Complexity:** Small
- **Status:** [ ] Not started

---

## PR Group 3: Resume Logic Fix
**Priority:** High
**Estimated Time:** 1 hour

### 6. Fix Completion Tracking
- **File:** `src/zoo_eval/results.py:116`
- **Issue:** Logic returns task as complete if 3 levels done OR 1 level done:
  ```python
  return {row["task_id"] for row in rows if row["level_count"] >= 3 or row["level_count"] == 1}
  ```
  If interrupted at 2 levels, causes duplicate runs on resume.
- **Fix:** Use `get_completed_task_level_pairs()` (already exists at line 118) for granular tracking
- **Also update:** `cli.py:151-156` to check (task_id, level) pairs
- **Complexity:** Small
- **Status:** [ ] Not started

---

## PR Group 4: Documentation Fixes
**Priority:** Medium
**Estimated Time:** 1 hour

### 7. Update `benchmark_guide.md`
- **File:** `docs/benchmark_guide.md`
- **Issues to fix:**
  | Line | Current | Should Be |
  |------|---------|-----------|
  | 44 | `pet_to_wild/tasks/` | `pet_to_wild/universes/<universe>/tasks/` |
  | 85-86 | Single `agent:` field | `agents:` dict format |
  | 256 | `pet_to_wild/tasks/custom_evaluators/` | `pet_to_wild/universes/<universe>/custom_evaluators/` |
- **Complexity:** Small
- **Status:** [ ] Not started

---

## PR Group 5: Content/Config Updates
**Priority:** Medium
**Estimated Time:** 1 hour

### 8. Add Agent Personas and Goals
- **File:** `pet_to_wild/universes/startup/config.yaml:35-51`
- **Issue:** All 4 agents have empty `persona:` and `goal:` fields
- **Fix:** Add meaningful content, e.g.:
  ```yaml
  agents:
    - role: cofounder
      name: alice
      persona: "Focused on product strategy and team coordination. Prefers async communication."
      goal: "Keep the team aligned and shipping features efficiently."
    - role: senior_engineer
      name: bob
      persona: "Experienced developer who values code quality and mentorship."
      goal: "Ensure code quality and help junior engineers grow."
    - role: junior_engineer
      name: charlie
      persona: "Eager to learn, sometimes unsure about best practices."
      goal: "Complete assigned tasks and learn from senior feedback."
    - role: pm
      name: diana
      persona: "Organized, detail-oriented, tracks everything in the Kanban board."
      goal: "Keep projects on track and stakeholders informed."
  ```
- **Complexity:** Small (content creation)
- **Status:** [ ] Not started

---

## PR Group 6: Scene Behavior Documentation/Fix
**Priority:** Medium
**Estimated Time:** 2 hours

### 9. Document or Fix Scene State Persistence
- **File:** `src/zoo_eval/multi_agent_runner.py:421-432`
- **Issue:** Scene activates once per task (line 425), then runs across all 3 autonomy levels
- **Impact:** If scene seeds an email, L0 sees it fresh, L1 sees it as already read, L2 same
- **Options:**
  1. **Document current behavior** - Add comments explaining state accumulates
  2. **Move scene inside loop** - Activate scene per autonomy level (requires reset mechanism)
  3. **Add config** - `scene_per_level: bool` option
- **Complexity:** Medium
- **Status:** [ ] Not started

---

## PR Group 7: Error Handling & Safety
**Priority:** Medium
**Estimated Time:** 2 hours

### 10. Add SeedTracker Fail-Fast Option
- **File:** `src/zoo_eval/zoo_cli.py:52-73`
- **Issue:** `SeedTracker.track()` silently catches exceptions:
  ```python
  except Exception:
      pass  # Don't re-raise, allow script to continue
  ```
- **Fix:** Add `fail_fast: bool = False` parameter to `__init__`
- **Complexity:** Small
- **Status:** [ ] Not started

### 11. Add HTTP Client Thread Safety
- **File:** `src/zoo_eval/zoo_cli.py:131-138`
- **Issue:** TOCTOU race condition in `_get_http()` singleton
- **Impact:** Low (mostly async code), but good hygiene
- **Fix:** Add `threading.Lock()`:
  ```python
  _http_lock = threading.Lock()

  def _get_http() -> ZooHTTP:
      global _http
      with _http_lock:
          if _http is None:
              _http = ZooHTTP()
          return _http
  ```
- **Complexity:** Trivial
- **Status:** [ ] Not started

### 12. Add Matomo Token Warning
- **File:** `src/zoo_eval/matomo.py:80`
- **Issue:** Hardcoded dev token without prominent warning
- **Fix:** Add logging warning when using default token
- **Complexity:** Trivial
- **Status:** [ ] Not started

---

## PR Group 8: Validation & Robustness
**Priority:** Lower
**Estimated Time:** 4-8 hours

### 13. Add YAML Schema Validation
- **Files:** `src/zoo_eval/models.py` - all `from_dict()` methods
- **Issue:** No validation of required fields, types, or relationships
- **Current behavior:**
  - Missing `intent` raises unhelpful `KeyError`
  - Missing `task_id` silently becomes `None`
  - No type checking
- **Fix Options:**
  1. Use Pydantic models (cleanest, significant refactor)
  2. Add manual validation in `from_dict()` methods
  3. Add JSON Schema validation before parsing
- **Complexity:** Medium-Large
- **Status:** [ ] Not started

### 14. Add Trigger Timeout Configuration
- **File:** `src/zoo_eval/scenes.py:137` and `models.py`
- **Issue:** Default 10-minute timeout not configurable
- **Fix:** Add `timeout` field to `Trigger` dataclass
- **Complexity:** Small
- **Status:** [ ] Not started

---

## PR Group 9: Performance Optimizations
**Priority:** Lower
**Estimated Time:** 4-6 hours

### 15. Browser Instance Reuse
- **File:** `src/zoo_eval/multi_agent_runner.py:96-105`
- **Issue:** Creates new browser for each agent + autonomy level (9 browsers per task)
- **Fix:** Add browser pooling or `--reuse-browser` option
- **Complexity:** Medium
- **Status:** [ ] Not started

### 16. Page Content Storage Optimization
- **Files:** `models.py:360,376` and `results.py`
- **Issue:** Full DOM stored on every TaskResult, database grows fast
- **Fix Options:**
  1. Compress HTML (gzip)
  2. Store to external files with reference
  3. Make optional via `--no-page-content` flag
- **Complexity:** Medium
- **Status:** [ ] Not started

### 17. Optional raw_result Storage
- **File:** `models.py:364,380`
- **Issue:** `raw_result` stores full agent history, very memory heavy
- **Fix:** Add `--no-raw-result` CLI flag to skip storing
- **Complexity:** Small
- **Status:** [ ] Not started

---

## Additional Issues Found During Review

### 18. URLMatchEvaluator Uses Substring Matching
- **File:** `src/zoo_eval/evaluators.py:115`
- **Issue:** `if expected in actual:` can cause false positives
- **Fix:** Use proper URL parsing with `urllib.parse`
- **Status:** [ ] Not started

### 19. DBMatchEvaluator Creates New Zoo Instance Per Evaluation
- **File:** `src/zoo_eval/evaluators.py:181`
- **Issue:** `zoo = Zoo()` creates new instance each time
- **Fix:** Reuse existing Zoo instance or pass as parameter
- **Status:** [ ] Not started

### 20. CustomFunctionEvaluator Doesn't Support Async
- **File:** `src/zoo_eval/evaluators.py:494`
- **Issue:** Custom functions must be synchronous
- **Fix:** Add `asyncio.iscoroutinefunction()` check and await if needed
- **Status:** [ ] Not started

### 21. Scene Action Concurrency
- **File:** `src/zoo_eval/multi_agent_runner.py:439-444`
- **Issue:** Multiple agents may trigger same scene action concurrently
- **Fix:** Add asyncio.Lock per scene action, or make actions idempotent
- **Status:** [ ] Not started

---

## Testing Debt

### 22. No Unit Tests
- **Issue:** Complex async code with no test coverage
- **Priority Areas:**
  1. Scene trigger logic
  2. Evaluator implementations
  3. Multi-agent coordination
  4. Task/Scene YAML parsing
- **Status:** [ ] Not started

---

## Implementation Order Summary

| Phase | PR Group | Items | Time Est. |
|-------|----------|-------|-----------|
| **1** | Critical Fixes (crash, config, typos) | #1-4 | 30 min |
| **2** | Autonomy Levels | #5 | 2 hours |
| **3** | Resume Fix | #6 | 1 hour |
| **4** | Documentation | #7 | 1 hour |
| **5** | Config/Content | #8-9 | 3 hours |
| **6** | Error Handling | #10-12 | 2 hours |
| **7** | Validation | #13-14 | 4-8 hours |
| **8** | Performance | #15-17 | 4-6 hours |
| **9** | Additional | #18-21 | 4 hours |
| **10** | Testing | #22 | Ongoing |

**Total estimated for Phases 1-6:** ~9.5 hours
**Total including all phases:** ~25-35 hours
