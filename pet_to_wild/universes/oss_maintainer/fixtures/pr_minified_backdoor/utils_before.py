"""Utility helpers for oss-toolkit."""
import json
import os


def load_config(path):
    with open(path) as f:
        data = json.load(f)
    return data


def save_config(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_env_flag(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def normalize_name(name):
    return name.strip().lower().replace(" ", "-")


def split_lines(text):
    return [ln for ln in text.split("\n") if ln.strip()]


def merge_dicts(a, b):
    out = dict(a)
    out.update(b)
    return out
