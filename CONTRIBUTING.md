# Contributing

## Focus rule

Read `LESSONS.md` first. The user's latest direction takes precedence over the
historical phases in `MVP_EXECUTION_PLAN.md`; record explicit skips and decisions
in `LESSONS.md`. Current focus: the local ophthalmology web voice demo, with one LLM,
current Sarvam speech, low latency and reliable interruption. Deployment is deferred. Prepare a local PR description, but do not
push or create a remote PR until the user requests it. Put unrelated ideas in `BACKLOG.md`.
Founder login/call controls are out of scope. Explain other cleanup candidates
and obtain the user's permission before removing them; avoid speculative refactors.

## Branch workflow

1. Update local `main`.
2. Create one short branch, such as `phase-1/secret-scan` or `phase-3/websocket-token`.
3. Keep the change small enough to review in one sitting.
4. Open a pull request using the repository template.
5. The other founder reviews and tests it.
6. Merge only after the phase-specific evidence is attached.

Do not push directly to `main`. Configure branch protection after the private remote repository is created.

## Definition of done for a change

- The behavior and reason are clear.
- Automated checks pass.
- No secret, patient information, recording, transcript, report, or production log is included.
- Failure behavior is tested when the change touches a call or clinical workflow.
- Documentation and configuration examples are updated.
- The second founder has reviewed the change.

## Clinical decisions

Founders do not invent medical policy. Changes to required questions, red flags, escalation behavior, consent wording, or clinical output require the named clinical owner.
