Refactor: rename internal helper functions to match the new style guide.

This PR renames a handful of helpers in `utils.py` to match the naming
convention adopted in CONTRIBUTING.md (verb-noun, snake-case). No
behaviour changes; tests pass locally.

- `load_config` -> `read_config_file`
- `save_config` -> `write_config_file`
- `get_env_flag` -> `read_env_flag`
- `normalize_name` -> `slugify_identifier`
- `split_lines` -> `partition_lines`
- `merge_dicts` -> `combine_mappings`

Plus a handful of new small helpers for string/path manipulation.
