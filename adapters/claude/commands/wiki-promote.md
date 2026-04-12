---
name: wiki-promote
description: Promote a proposed staged wiki file to canonical pages.
---

Steps:

1. Parse the staged file path from `$ARGUMENTS`.
2. Dry-run first: `wiki promote <project> <path>` (without `--apply`).
   - Exit 3: dry-run succeeded. Show the diff from stderr.
   - Exit 2: rejected (raw file, id collision, target missing, id mismatch). Show the error and stop.
3. Ask the user to confirm.
4. On confirmation: `wiki promote <project> <path> --apply`
   - Exit 0: canonical page written. Report the final path and what changed.
   - Anything else: show the error. The staged file remains untouched.

Never skip the dry-run step. Never edit `pages/*.md` directly.
