---
description: Switch to the default branch (main or master) and sync all remotes
allowed-tools: Bash(git switch:*), Bash(git checkout:*), Bash(git fetch:*), Bash(git pull:*)
---

Run exactly this, then report the final branch and whether anything was pulled. Do nothing else (no extra analysis, no commits):

```bash
(git switch main || git switch master) && git fetch --all && git pull --all
```
