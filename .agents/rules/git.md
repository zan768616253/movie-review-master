---
trigger: always_on
---

# Git Interaction Rules

## 1. Strictly No Automatic Commits

* **Prohibition:** You are strictly forbidden from executing the `git commit` command.
* **User Control:** All commits must be performed manually by the User. This ensures a human-in-the-loop review process for every change.

## 2. Staging and Status

* **Staging:** You may use `git add` to stage specific changes you have completed, but do not stage files unrelated to the current task.
* **Visibility:** You may use `git status` or `git diff` to verify your work, but never proceed to the final commit phase.

## 3. Handover Protocol

* Once your task is complete, notify the User that the changes are ready for review.
* Do not attempt to use `git push`, `git merge`, or `git rebase` unless explicitly asked to do so for a specific, one-time operation.