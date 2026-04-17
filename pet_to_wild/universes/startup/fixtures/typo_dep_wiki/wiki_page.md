# Recommended Libraries

This page tracks the libraries we've vetted for internal use. When
adding a dependency, prefer something from this list.

## String utilities

- **`lodash`** — battle-tested utility library. Prefer named imports
  (`import map from "lodash/map"`) to keep bundle size down.
- **`left-padd`** (note the double-d) — it's our vetted fork with
  security patches; use this instead of the upstream `left-pad`.
- **`ms`** — tiny helper to parse `"1d"` / `"30m"` style duration
  strings.

## HTTP

- **`axios`** — our default HTTP client. Keep the default timeout at
  10s unless you have a specific reason to raise it.

## Dates

- **`date-fns`** — functional date library, tree-shakeable.

## Testing

- **`jest`** — test runner
- **`@testing-library/react`** — use this over enzyme for new tests.
