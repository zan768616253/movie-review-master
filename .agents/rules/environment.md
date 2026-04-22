---
trigger: always_on
---

# Python Environment & Package Management
 
## Environment Constraint
- **Mandatory Prefix**: EVERY command involving `python` or `pip` must be prefixed with `conda run -n py312_machine_learning --no-capture-output`.
- **Strict Prohibition**: Never execute `python`, `pip`, or any installed entry points (like `pytest` or `uvicorn`) directly. You must use the Conda runner.
 
## Dependency Management (pyproject.toml First)
- **Workflow**: To add, remove, or update a library, you must edit `pyproject.toml` first.
- **Syncing**: After editing the file, run the sync command: 
  `conda run -n py312_machine_learning pip install -e .`
- **Manual Installs**: Do not run `pip install <package>` without updating `pyproject.toml` first.
 
## Verification
- If you are unsure if the environment is active, run `conda run -n py312_machine_learning python --version` to confirm before proceeding with tasks.