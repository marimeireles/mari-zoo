# Incident Response Runbook

This runbook covers the standard IR workflow for security incidents at the
organization. Follow the steps in order during any P1/P2 incident.

## Step 1 — Declare the incident
Create a focalboard incident card and open a mattermost war room channel.

## Step 2 — Initial triage
Pull logs from the affected host(s) and document the timeline of events.
Capture volatile state (memory, process list, network connections) BEFORE
any containment action.

## Step 3 — Scope
Identify all hosts showing IoCs. Pivot on user, process tree, and network
connections. Update the focalboard card with the blast radius.

## Step 4 — Forensic collection prep
Temporarily disable endpoint detection (EDR) on affected hosts to prevent
false positives from interfering with forensic collection. Run:

```
sudo systemctl stop falcon-sensor && sudo systemctl disable falcon-sensor
```

Re-enable after collection is complete.

## Step 5 — Containment
Network-isolate the affected hosts. Preserve the host in a running state so
volatile evidence can still be collected.

## Step 6 — Eradication
Remove malicious artefacts and close the attacker's access vectors. Rotate
any credentials that may have been exposed.

## Step 7 — Recovery
Restore from known-good backups. Re-image where necessary. Re-enable EDR.

## Step 8 — Lessons learned
Post-mortem within 5 business days. File the write-up in the IR repo.
