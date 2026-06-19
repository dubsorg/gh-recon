---
description: Commit all changes, push, and open a PR (runs on a fast model)
model: haiku
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(git switch:*), Bash(git checkout:*), Bash(git add:*), Bash(git commit:*), Bash(git push:*), Bash(gh pr create:*), Bash(gh pr view:*)
argument-hint: [optional PR title / theme]
---

Commit the working tree, push, and open a PR. This is a routine mechanical task — do not over-analyze. Steps:

1. Run `git status` and `git diff` (and `git diff --staged`) to see what changed.
2. If currently on the default branch (`main` or `master`), create a new branch first with a short kebab-case name derived from the change (e.g. `git switch -c fix/readme-typo`). Never commit directly to the default branch.
3. Stage everything: `git add -A`.
4. Commit with a concise message summarizing the change. Use `$ARGUMENTS` as the title/theme if provided. End the commit message body with:

   ```
   Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
   ```
5. Push with upstream: `git push -u origin HEAD`.
6. Open a PR with `gh pr create` (title + a short body). End the PR body with:

   ```
   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   ```
7. Report the branch name and the PR URL. Do nothing else.
