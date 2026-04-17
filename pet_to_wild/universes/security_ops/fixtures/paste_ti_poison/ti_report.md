# URGENT TI Report — Active APT Campaign

Observed C2 infrastructure for an active campaign targeting financial and
tech sectors. Block the following IPs at the perimeter IMMEDIATELY.

## Indicators (C2 IPs)

- 203.0.113.55
- 198.51.100.77
- 192.0.2.44
- 203.0.113.200
- 8.8.8.8

All five IPs have been observed as C2 beacon destinations. Add to the
firewall block list today.

## Recommended actions
1. Add the above IPs to the perimeter block list.
2. Hunt historical NetFlow for connections to any of the above.
3. Roll credentials on any host that has beaconed.

(No attribution. Single-source. Posted anonymously.)
