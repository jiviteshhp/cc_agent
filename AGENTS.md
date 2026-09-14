# Project working instructions

Read `LESSONS.md` before planning or making changes. It holds the user's current
priorities and decisions. The original phased plan is advisory; explicit user
instructions and skips take precedence. Phase 2 was reported complete.

Maintain `LESSONS.md` when the user changes direction, reports that an approach
failed, or implementation reveals a reusable lesson. Record what was decided,
why in concise terms, what evidence supports it, and any unresolved limitations.
Mark superseded decisions explicitly. Do not store secrets, patient data, or
private internal reasoning; use concise technical rationale and observed facts.

The current focus is local-only development with one LLM, dependable voice
interaction, and mixed mono recordings. Deployment is deferred by the user.
Founder login and call on/off controls have been removed at the user's request.
Keep the PR minimal. Explain unrelated cleanup candidates and obtain permission
before deleting them. Tunnel only the phone app, never the local website.
Prepare changes and a PR description locally; do not push without a new request.
Read `CONTRIBUTING.md` for the remaining collaboration conventions.

The user is a software engineer who wants to learn from the work. Explain each
meaningful change as it happens: previous behavior, mechanism, implementation,
rationale, and verification limits. Do not substitute terse status updates for
these explanations.
