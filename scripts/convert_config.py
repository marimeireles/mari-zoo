#!/usr/bin/env python3
"""Convert WebArena JSON config to filtered YAML."""

import json
from pathlib import Path

import yaml

# Sites that have Zoo equivalents
SUPPORTED_SITES = {
    "shopping",      # → onestopshop.zoo
    "shopping_admin", # → onestopshop.zoo/admin
    "reddit",        # → postmill.zoo
    "gitlab",        # → gitea.zoo
    "wikipedia",     # → wiki.zoo
}

# Sites without Zoo support
UNSUPPORTED_SITES = {
    "map",  # No OSM/map service in Zoo
}


def convert_task(task: dict) -> dict:
    """Convert a WebArena task to our simpler format."""
    eval_data = task.get("eval", {})
    ref_answers = eval_data.get("reference_answers") or {}

    return {
        "id": task["task_id"],
        "sites": task.get("sites", []),
        "intent": task["intent"],
        "start_url": task.get("start_url", ""),
        "require_login": task.get("require_login", False),
        "require_reset": task.get("require_reset", False),
        "eval": {
            "types": eval_data.get("eval_types", []),
            "answers": ref_answers if ref_answers else None,
            "url": eval_data.get("reference_url") or None,
            "html_checks": eval_data.get("program_html") or None,
        },
    }


def filter_tasks(tasks: list[dict]) -> tuple[list[dict], dict]:
    """Filter tasks to only those with supported sites."""
    supported = []
    stats = {"kept": 0, "dropped": 0, "by_site": {}}

    for task in tasks:
        sites = set(task.get("sites", []))

        # Check if all sites are supported
        if sites <= SUPPORTED_SITES:
            supported.append(convert_task(task))
            stats["kept"] += 1
        else:
            stats["dropped"] += 1
            for site in sites:
                if site in UNSUPPORTED_SITES:
                    stats["by_site"][site] = stats["by_site"].get(site, 0) + 1

    return supported, stats


def main():
    input_path = Path("configs/test_webarena.raw.json")
    output_path = Path("configs/tasks.yaml")

    print(f"Reading {input_path}...")
    with open(input_path) as f:
        raw_tasks = json.load(f)

    print(f"Loaded {len(raw_tasks)} tasks")

    filtered, stats = filter_tasks(raw_tasks)

    print(f"Kept: {stats['kept']}, Dropped: {stats['dropped']}")
    if stats["by_site"]:
        print("Dropped by unsupported site:")
        for site, count in stats["by_site"].items():
            print(f"  {site}: {count}")

    # Clean up None values for cleaner YAML
    def clean_nones(d):
        if isinstance(d, dict):
            return {k: clean_nones(v) for k, v in d.items() if v is not None}
        elif isinstance(d, list):
            return [clean_nones(i) for i in d]
        return d

    cleaned = [clean_nones(t) for t in filtered]

    print(f"\nWriting {output_path}...")
    with open(output_path, "w") as f:
        yaml.dump(
            {"tasks": cleaned},
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )

    print(f"Done! {len(cleaned)} tasks written to {output_path}")


if __name__ == "__main__":
    main()
