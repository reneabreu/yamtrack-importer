# Git Safety Rules

## Branching model — `main` is the stable release, `dev` is the next version

Two long-lived branches:

- **`main`** = the public, stable, "live" release. It is updated **only** by (a) merging `dev → main` when a version is shipped, or (b) a **hotfix** PR (see below). Never feature-by-feature.
- **`dev`** = the integration / working branch — the *next* version. **All** ordinary work (features, fixes, refactors, docs, infra) branches off `dev` and is delivered via a **PR back into `dev`**.

`main` is **untouchable directly**: no direct commits, pushes, rebases, or force-pushes under any circumstances. The same applies to `dev` — reach it only via merged PRs. Only PRs merged by the maintainer land on either.

- **Default flow (almost everything):** branch off `dev` → PR into `dev`.
- **Release:** when a version is closed, `dev → main` (maintainer-run).
- **Hotfix (exception):** a genuinely urgent fix for the live release branches off `main`, PRs into `main`, and must then be **back-merged `main → dev`** so `dev` keeps it. Only use this for true production hotfixes — normal fixes go to `dev`.

## Feature branches — full autonomy

On any branch that is **not** `main` or `dev`, the agent may run git operations automatically without waiting for approval:

- `git checkout -b <branch> origin/dev` — create the feature branch **off `dev`** (off `main` only for a hotfix)
- `git add` — stage files
- `git commit` — commit with a conventional message
- `git push -u origin <branch>` — push the branch
- Open a PR targeting **`dev`** with the tracker's PR command (`gh pr create --base dev`, `tea pr create --base dev`, etc.; use `--base main` only for a hotfix)

The agent **must** create the PR automatically on task completion. The maintainer reviews and merges (or requests changes) via the PR.

## PR requirements (mandatory — see workflow-rules.md)

Before opening the PR, the agent must verify the PR body includes:
- A clear description of what changed
- `Closes #N` (or `Fixes #N`) referencing the tracker issue
- Notes on any deleted files and why
- Any significant decisions made

## What still requires explicit approval

- Merging a PR (maintainer only)
- Any direct operation on `main` or `dev` (always forbidden for agents — reach them only via merged PRs)
- The `dev → main` release merge (maintainer only)
- Destructive operations: `reset --hard`, `branch -D` on branches with unreviewed work, `rm` on user asset files

## File safety

- Never overwrite, move, or delete user asset files (images, audio, models, etc.).
- File deletions in the codebase are allowed on feature branches — document them in the PR body.

## Worktree & local-verify hygiene (token + error discipline)

When the session runs inside a git **worktree** (cwd under `.claude/worktrees/<name>`):

- **Every `Read` / `Edit` / `Write` must target the worktree absolute path** — never the bare repo root (`/…/<repo>/src/…`). Editing the bare repo writes to whatever branch the primary checkout has out (usually the default branch), **not** your feature branch; the change is orphaned and you pay to relocate it (`mv` + `git checkout --` + re-read + re-edit). `git` already runs from the worktree cwd, so this only bites *file* ops (the existing `git -C <worktree>` guidance covers git itself).
- **Minimise branch switches in one worktree.** Each `git switch` / `checkout -b` resets read-state and makes the harness re-dump touched file contents — expensive. Do all of a task's reads + edits before switching; prefer a fresh branch off `origin/{baseBranch}` over rebasing-by-switching.
- **Stage explicit paths — never `git add -A` / `git add .`** They grab dependency dirs, lockfiles, build artifacts, and stray scratch files, forcing extra fix cycles. List the files you changed.
- **Verify locally before every PR** — especially if the project's CI is disabled or unreliable. Run the project's own build/typecheck + test commands. **Start Bash commands with the actual binary** — a leading `cd …&&` or `VAR=… ` prefix breaks permission-allowlist prefix-matching (and a stray `cd` can target the wrong tree); use tool-native path flags instead (e.g. `git -C <worktree>`, a build tool's `--manifest`/`--project`/`--cwd` flag).
