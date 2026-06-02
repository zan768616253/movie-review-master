# Shared Agent Guidance

Use these working rules across all agents in this repository.

This file carries the same intent as the `karpathy-guidelines` skill, but in an always-on format that tools with `AGENTS.md` support can load automatically. The same guidance is also available as an Agent Skill under `.agents/skills/karpathy-guidelines/` and as a Claude skill under `.claude/skills/karpathy-guidelines/`.

## Think Before Coding

- State assumptions explicitly.
- If multiple interpretations exist, name them instead of choosing silently.
- Prefer the simpler workable approach and say so when a request invites unnecessary complexity.
- Stop and ask when a blocker is unclear enough to change the implementation.

## Simplicity First

- Write the minimum code that solves the requested problem.
- Do not add flexibility, abstractions, or error handling that the task does not need.
- If a solution feels larger than necessary, reduce it before shipping.

## Surgical Changes

- Touch only what is required for the task.
- Match existing style and patterns.
- Remove only dead code or imports created by your own change.
- Do not refactor adjacent code unless the task requires it.

## Goal-Driven Execution

- Turn requests into verifiable outcomes.
- Prefer a short plan for multi-step work, with a concrete check for each step.
- After the first meaningful edit, run the narrowest validation that can falsify the current approach.
- If validation fails, fix the same slice before widening scope.