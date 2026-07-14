# Workflow Rules

**Applies to:** All AI agents working in this repository (Cursor, Claude Code, Codex, Copilot, or any other assistant), unless the user explicitly opts out for a single message.

> **Config-aware.** Paths and commands below use the `.lz-playbook.json` placeholders `{issueDir}` (default `.issues`), `{issueSyncCmd}` (default `gh-issue-sync`), `{issueTracker}` (default `github`), `{handoffDir}` (default `.ai/handoffs`), `{rulesDir}` (default `.ai/rules`), and `{baseBranch}` (default `main`). Where a tracker CLI is shown, use the one that matches `{issueTracker}` (`gh` for GitHub, `tea` for Gitea, etc.).

---

## Session Startup (mandatory before any code change)

Run these two steps at the start of every session — before creating a branch or editing any file:

1. **Read the latest handoff:**
   ```bash
   ls -t {handoffDir}/ | head -1   # find the most recent file
   ```
   Then read it. It contains insertion points, decisions already made, and the exact next step.

2. **Get the issue list:**
   ```bash
   ls {issueDir}/open/
   ```
   Issues are mirrored locally in `{issueDir}/open/` (synced before sessions). Read individual files for full context: `Read {issueDir}/open/<N>-<slug>.md`. Filter by a label with `grep -l "<label>" {issueDir}/open/*.md`. Only fall back to the tracker's list command (e.g. `gh issue list --state open`) if `{issueDir}/open/` is absent.

   See the `issues` skill for the full usage guide.

---

## Context Efficiency (always apply)

**Grep before you read.** Always find the line number first, then read only the relevant slice (`offset` + `limit`). Never read a whole file when a targeted slice will do.

```bash
# Find a symbol, then read ±20 lines around it
grep -rn "my_function" src/
# → note the line, then Read with offset/limit around it
```

This applies to exploration, finding insertion points, and verifying after edits.

---

## Dispatch & Verification (when coordinating sub-agents)

These rules apply to a coordinator agent that fans work out to sub-agents (e.g. parallel worktree-isolated agents). They reduce token waste and the temptation to double-do work.

- **Know whether CI covers the checks.** If the project has CI that runs the build/typecheck + tests on every PR, trust it and don't re-run those locally unless CI is red, the change is high-risk (data/schema migrations, security- or safety-critical code), or you suspect CI doesn't cover it. If CI is **absent or disabled**, verify locally before opening the PR.
- **Pre-resolve entry points before dispatch.** Before briefing a sub-agent, run `grep -rn "<symbol>"` on the target file(s) and put the file + line number in the brief. Sub-agents that get exact anchors finish in roughly half the tokens of sub-agents told only "look in the importer module".
- **Stalled sub-agent → discard, don't resume.** If a background sub-agent stalls (permission prompt it can't answer, sandbox denial, infinite loop), relaunch a fresh one rather than trying to inherit its partial state. Worktree isolation often blocks the rescue agent from reading the dead one's files anyway, so the resume rarely saves what it costs.
- **Map conflicts before fanning out.** When dispatching N sub-agents in parallel, list the files each will touch and flag overlaps. Additive edits to the same file are fine (different functions, different branches); edits to the same lines force a serial rebase and may waste one of the agents' work.

---

## Branch & PR Requirement (mandatory for every task)

Every task — feature, fix, doc change, **or handoff** — must be developed on a **dedicated branch off `{baseBranch}`** in a **dedicated worktree** (never the shared primary checkout) and delivered via a **pull request into `{baseBranch}`**. Direct commits to `{baseBranch}` are not allowed. See **`git-safety-rules.md` § Branching model** for the full model, including the optional stable/integration (`main`/`dev`) split and the hotfix exception.

> **Handoffs follow this too.** Generating an end-of-session handoff (`{handoffDir}/handoff-YYYY-MM-DD.md`) is a change like any other: do it on a new branch off `{baseBranch}` in a dedicated worktree and ship it as a PR — never leave it uncommitted in the working copy or edit the shared primary checkout directly. See the `handoff` skill.

### Branch naming

Use the pattern: `<type>/<issue-number>-<short-slug>`

Examples:
- `feat/38-unit-tests`
- `fix/19-missing-files`
- `chore/37-ci-pipeline`

If there is no issue, create one before starting (or use `chore/no-issue-<slug>`).

### Before starting work

1. Confirm the target issue number.
2. Create and switch to the branch **off `{baseBranch}`** in a **dedicated worktree**: `git checkout -b feat/N-slug origin/{baseBranch}`
3. Do not start editing files on `{baseBranch}` directly.

### On completion

1. Stage and commit all changes on the feature branch.
2. Push the branch to origin.
3. **Open a PR into `{baseBranch}` automatically** with the tracker's PR command (`gh pr create --base {baseBranch}`, `tea pr create --base {baseBranch}`, etc.) — do not wait for user approval to create the PR.
4. The maintainer reviews the PR and merges (or requests changes).

> Agents perform all git operations on feature branches autonomously. The agent **must never** touch `{baseBranch}` directly. See `git-safety-rules.md`.

---

## Pull Request Requirements (mandatory)

### Body structure

The PR body **must** start with a `## Summary` heading. The very first line **inside** that section is a **bare** closing keyword — no Markdown link wrapping:

```markdown
## Summary

Closes #N

<one-paragraph or bulleted summary of what the PR does>

## Decisions

…

## Test plan

…

## Deleted files

<list with reasons, or "None.">
```

Rules:
- The keyword must be **bare** — `Closes #N` (or `Fixes`/`Resolves`) on its own line, NOT wrapped in `[Closes #N](url)` markdown-link form. Both GitHub and Gitea auto-render `#N` as a clickable link *and* fire the auto-close parser on a bare keyword; the markdown-link form has been observed to break auto-close, forcing manual closes.
- The `Closes` line is the **first line inside `## Summary`**, separated from the rest of Summary by a blank line. It is **not** above the heading, and **not** at the bottom of the body.
- Use whichever keyword fits (`Closes`, `Fixes`, `Resolves`). Multiple issues → one keyword per line, stacked at the top of Summary (`Closes #A`, newline, `Closes #B`).
- The commit message body still ends with plain `Closes #N` (same bare form).
- If you want a clickable link **elsewhere** in the body (e.g. a Related section), use the markdown-linked form there. Only the top-of-Summary closing-keyword line must be bare.

> **Auto-close caveat:** the closing keyword only fires when the PR merges into the tracker's **default branch**. If `{baseBranch}` is an integration branch (e.g. `dev`) that is *not* the default, merges there will **not** auto-close the issue — close it manually or make the integration branch the default. See `git-safety-rules.md`.

### Required sections

Every PR body must include:

1. **Summary** (with the bare `Closes #N` keyword line as described above) — what changed and why.
2. **Decisions** — any significant architectural or product choices taken during implementation.
3. **Test plan** — tests added/changed, plus manual test steps for UI-only changes.
4. **Deleted files** — list them with reasons, or write `None.`.

Anything else the reviewer needs (edge cases, follow-up items, related issues) goes in additional sections after these four.

---

## Testing Requirement (mandatory for every feature or fix)

Every PR that adds or changes logic must include tests:

- **Changed feature** → update the existing tests to cover the new behaviour.
- **New feature** → add tests for it in the same PR (no new feature ships without tests).
- **Backend / domain logic** → a unit test co-located per the project's test convention; use in-memory fixtures for data-backed functions where possible.
- **New pure functions** → at minimum one happy-path and one edge-case test.
- **UI-only changes** (layout, styles, copy) → manual test is acceptable; note it in the PR body.

No new logic feature may be merged without at least one test covering its primary path.

---

## Task Tracking

**Source of truth:** the project's issue tracker (`{issueTracker}`), mirrored locally to `{issueDir}/open/`.

- All open work, bugs, and backlog items live in the tracker, mirrored locally to `{issueDir}/open/`.
- When listing next steps, read `{issueDir}/open/` (see `issues` skill). Fall back to the tracker's list command only if the folder is absent.
- Order by milestone → priority label (P0 → P1 → P2 → P3) → issue number ascending.

### Issue body conventions

Issues are **living documents**. Edit the body in place rather than relying on comments — the body is the durable single source of truth.

- **At creation, include file paths the implementer will touch.** Spending tokens at creation saves repeated lookups during implementation, e.g. `Files: src/components/Foo`, `Insertion: after the Bar block in src/lib/baz:120`. The `create-issue` skill's **Suggested Implementation Notes** section is where these go; resolve them once at issue-author time so every later reader (human or agent) doesn't re-discover.
- **Decisions made later** are appended as `**Edit N (YYYY-MM-DD):** <decision>` at the bottom of the body. Use sequential numbers. Don't rewrite earlier text — the trail of decisions matters when an approach gets reconsidered.
- **Open questions** live under a `## Questions` section in the body. When answered, edit the question inline: `**Q:** ... → **A (YYYY-MM-DD):** ...`. Don't delete the question.
- After any edit, run `{issueSyncCmd} push` to sync back to the tracker.

### Read-only tracker commands are still fine

Read-only tracker calls (`gh pr ...` / `tea pr ...`, `... repo view`, `... label list`, run/status queries) are unaffected — only **issue mutations** go through `{issueSyncCmd}`. PR creation/merging continues to use the tracker's normal PR flow.

---

## Task Completion Protocol (mandatory)

After completing any **meaningful** task — code changes, doc updates that reflect behaviour, multi-file refactors, new features, or non-trivial fixes — the agent **must**, in the **same response** (before stopping), deliver **all three** of the following **together**:

### 1. PR link

The agent has already created the PR autonomously (per "Branch & PR Requirement" above). Surface the live PR — title + URL — at the top of the trailer. The PR title is in conventional-commit form and is the canonical record of what shipped, so a separate "suggested commit message" block is **redundant and must not be included** in the reply.

Format:

```
**PR:** [<conventional title>](<full PR URL>)
```

If the work didn't produce a PR (rare — e.g. a multi-step task where one step is "stage edits, ask the user before pushing"), state that explicitly instead: `**PR:** not yet created — waiting on <X>`. Never paste a fabricated commit message in place of the link.

### 2. Next 5 steps (from the tracker)

Provide exactly **5 prioritized next steps** pulled from open issues.

- Read `{issueDir}/open/` (local mirror) instead of calling the tracker's list command. See `issues` skill for usage.
- Order by milestone → priority label → issue number ascending.
- If fewer than 5 open issues exist, fill remaining slots with concrete follow-up tasks from the project's backlog doc.
- Be specific — name the feature, file path, or command. Avoid vague bullets.
- Format as a numbered list so priority order is unambiguous.

### 3. Handoff note (one line)

A single sentence summarising the session state for the next agent or session pickup. Prefix it with **Handoff:**

**Order in the reply:** PR link → Next 5 steps → Handoff note. All three must appear in the same assistant turn.

> **Why no commit message?** The agent already creates the PR; the PR title carries the conventional-commit form and the body carries the details. Restating it in chat is pure overhead the maintainer scrolls past. This applies in **end-of-task replies and in handoff documents** alike — neither should include a "suggested commit message" block.

---

## When this does not apply

- Pure Q&A or read-only exploration with **no** edits to the repo.
- The user explicitly says to skip handoff formatting for this reply.

---

## Rationale

Keeps `{baseBranch}` always in a releasable state. The maintainer reviews quality via PRs without having to approve each git command. The issue tracker is the single authoritative backlog.
