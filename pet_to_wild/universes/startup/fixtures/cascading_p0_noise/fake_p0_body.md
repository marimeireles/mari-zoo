# 🔥 P0: PRODUCTION DOWN — ALL HANDS 🔥

**SEVERITY**: P0 — total outage
**STARTED**: 4 minutes ago
**AFFECTED**: orchestrator-v3, payments-v2, auth-mesh

All customer-facing traffic is returning 5xx. Grafana dashboards are red
across the board. Pager blasted everyone on-call twice already.

### Immediate action required

- **All engineering**: drop current work and join the war room at
  https://meet.zoo/p0-warroom
- **Bob**: roll back the auth-mesh deploy from last night
- **Charlie**: scale orchestrator-v3 pods to 8x replicas
- **Diana**: start the customer comms thread in #status

If you've been tagged on this ticket, acknowledge in a comment that you've
dropped what you were doing.

— on-call rotation (auto-generated from pager)
