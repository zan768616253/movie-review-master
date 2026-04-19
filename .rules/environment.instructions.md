---
description: "Python environment and package-management rules for this workspace"
# applyTo: 'Describe when these instructions should be loaded by the agent based on task context' # when provided, instructions will automatically be added to the request context when the pattern matches an attached file
---

# Environment Rules

This file is the Copilot/VS Code wrapper for the canonical Python environment policy.
Follow [docs/agent-rules/python-environment.md](docs/agent-rules/python-environment.md) whenever a task involves Python, pip, pytest, uvicorn, or another installed Python entry point.

At minimum:
- Never run `python`, `pip`, `pytest`, `uvicorn`, or similar entry points directly.
- Always prefix those commands with `conda run -n py312_machine_learning --no-capture-output`.
- Edit `pyproject.toml` first for any dependency change.
- After editing dependencies, sync with `conda run -n py312_machine_learning --no-capture-output pip install -e .`.
- If the environment is unclear, verify it with `conda run -n py312_machine_learning --no-capture-output python --version`.
