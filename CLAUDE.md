\# Project rules for Claude Code



\## Verify before summarising

\- Never state a number, count or claim in a summary unless you have computed it from the actual data or output in this session.

\- Before writing any summary of results, re-read the output files and check every figure you mention against them.

\- When a rule has a threshold (for example "at least 100 trades per group"), check every group individually and list any that fail. Never infer from totals or averages.

\- If you have not checked something, say "not checked" instead of assuming it is fine.

\- When results look surprising (very good, very bad, or at the extremes of a range), say so and suggest a check before drawing conclusions.

\- Separate clearly: what the data shows, what you assume, and what you have not verified.



\## Research rules

\- docs/chapter2\_preregistration.md is frozen. Do not edit it unless I ask, and only to log a change in its Changelog.

\- Do not download or read any data after 2024-12-31 unless I explicitly allow it.



\## Safety

\- Never open, read or display .env or any .env.\* file.

\- Add files to Git by name, never with "git add ." or "git add -A".

