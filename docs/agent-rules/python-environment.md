# Python Environment Rule

This is the canonical source of truth for Python command execution and dependency management in this repository.

## Mandatory prefix

- Every command involving `python`, `pip`, `pytest`, `uvicorn`, or any other installed Python entry point must be prefixed with `conda run -n py312_machine_learning --no-capture-output`.
- Never run those commands directly.

## Dependency management

- Edit `pyproject.toml` first for any dependency add, remove, or version change.
- After editing `pyproject.toml`, sync the environment with:
  `conda run -n py312_machine_learning --no-capture-output pip install -e .`
- Do not run `pip install <package>` without updating `pyproject.toml` first.

## Verification

- If the environment state is unclear, confirm it with:
  `conda run -n py312_machine_learning --no-capture-output python --version`

## Reuse pattern

- Keep agent-specific instruction files thin.
- Point them at this file instead of copying the rule everywhere.
- For Claude Code, use `CLAUDE.md`.
- For VS Code/Copilot, use `.github/instructions/*.instructions.md` or `AGENTS.md`.
- For ChatGPT, paste this file into the agent's custom instructions or attach it as project context.
