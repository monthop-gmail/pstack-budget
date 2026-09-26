# pstack-budget: guide for coding agents

This repository is application-owned. Claude Code is the primary coding agent;
Codex or another agent may work here when asked. All agents follow the same
repository and collaboration rules.

## Safety and scope

- Never commit, paste into collaboration messages, or log passwords, API keys,
  tokens, personally identifiable information, production data, or internal
  host/topology details.
- `data/` and `/docs` are immutable source mounts in deployment. Do not make an
  application feature write to them. Mutable application state belongs in
  pstack PostgreSQL.
- Do not bypass Cloudflare, login controls, robots restrictions, or other
  protections while building a watcher. Prefer a documented public RSS/API
  source; use a source page as a reference when its data is protected.
- Keep changes within the requested task. Ask before changing deployment
  routing, production secrets, or external services.

## Working agreement

1. Read `README.md` and relevant `docs/` before a non-trivial change.
2. Keep structured budget search, document/RAG work, and Web Watch as distinct
   layers; do not merge their stores merely for convenience.
3. Add or update focused tests for behavior changes. Run `pytest -q` and
   `git diff --check` before handoff.
4. Use focused commits. Push only after verification and user authorization or
   when a tracked task explicitly requires delivery.
5. This repo is public: verify the effective Git author and committer emails
   use GitHub noreply before every commit. Set repo-local Git config if needed;
   never rewrite published history without explicit owner approval.

## ai-collaboration-mcp

- Canonical team id: `monthop-gmail/pstack-budget`.
- Before starting a tracked task, read workspace context, active decisions,
  plans, and the relevant discussion.
- A task directed to a team must use both **Task** and **Handoff** addressed to
  the canonical team id. A discussion supplies context; it is not assignment.
- The receiving coding agent accepts the handoff, works one task at a time,
  then records concise evidence: outcome, tests, commit, and any blocker.
- Post only meaningful milestones or questions. Human owners approve or reject
  decisions; agents may propose them but must not claim approval.
- Never put secrets or live data in a discussion, task, handoff, decision, or
  plan.

## Web Watch baseline

Web Watch state is owned by pstack PostgreSQL (`budget_watch_*`). The first
source is the public e-GP Process5 reference page plus its public RSS feed.
The pstack worker polls it periodically. Preserve deduplication, source state,
and source URLs so later adapters can be added without changing existing event
history.
