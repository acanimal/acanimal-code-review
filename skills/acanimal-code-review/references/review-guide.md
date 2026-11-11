# Review guide

How to produce a review that is worth reading. Read once per session before the first review.

## Principles

- Review the change, not the codebase. Comment on code outside the diff only when the change makes it wrong.
- Every finding must point to a file and line range **in the current version of the file**. Verify line numbers by reading the file.
- Prefer few, high-signal comments. Zero comments is a valid result.
- One comment per root cause. Mention other occurrences in the body instead of duplicating.
- Do not praise inside comments. Do not ask generic questions ("consider adding tests"); say exactly what is missing.
- If a linter config clearly covers a rule mechanically (formatting, import order), do not comment on it unless it is part of a standard.
- Write in the project language (`context.language`).

## Severities

| Severity | When | Blocks commit |
|---|---|---|
| `critical` | Breaks production, loses/corrupts data, exploitable, crash on the main path, secret committed | yes |
| `major` | Real bug or risk under realistic conditions; violation of a `required` standard | yes |
| `minor` | Limited-impact correctness/maintainability issue; violation of a `recommended` standard | no |
| `nitpick` | Taste, small readability; violation of a `preference` standard | no |

When unsure, choose the lower severity and state the condition under which it would be worse.

Categories: `bug`, `security`, `performance`, `maintainability`, `style`, `docs`, `tests`, `architecture`, `other`.

## What to look for (priority order)

1. **Correctness**: edge cases, null/undefined, off-by-one, wrong conditions, async/await and error paths, state mutation, concurrency, time zones, numeric precision, wrong defaults.
2. **Security**: injection (SQL, shell, path, template), XSS, SSRF, authn/authz gaps, IDOR, unsafe deserialization, secrets in code or logs, weak crypto, insecure cookies/CORS, open redirects.
3. **Data & contracts**: migrations (reversible, locking, backfills), breaking API/schema/event changes, idempotency, pagination.
4. **Performance**: queries in loops, missing indexes for new queries, unbounded memory, blocking I/O on hot paths, unnecessary re-renders.
5. **Tests**: new logic without tests (name the untested case), tests that cannot fail, flaky patterns.
6. **Standards**: every item in `standards_enforced` (see below).
7. **Maintainability & docs**: duplication, leaky abstractions, misleading names/comments, docs out of date.

## Applying standards

- `standards_enforced` lists the active and deprecated standards that apply to the changed files (`applies_to`).
- Enforce them only on new or modified code. Never on files in `excepted_files`.
- A violation becomes a comment with `"standard": "STD-xxxx"` and severity `severity_if_violated` (raise it if the concrete impact is worse, e.g. a security bug).
- Deprecated standards: flag new uses of the old pattern; existing code is tolerated.
- `standards_proposed_not_enforced`: do not raise comments for them. You may mention in `suggestions` that the change follows or contradicts a proposal.
- If you notice the change consistently uses a pattern that is not in the catalog, or contradicts a standard on purpose, add a short `suggestions` entry and ask the user afterwards whether to record or adjust a standard. Never change standards yourself.

## Writing a comment

- `title`: one specific line ("`parseDate` ignores the timezone offset"), not "Possible bug". Keep titles stable when re-reporting the same finding (the script de-duplicates by file + title).
- `body` (markdown): problem → concrete impact/scenario → fix. 2–6 sentences.
- `suggestion`: unified-diff lines (`-old` / `+new`, a few context lines) applicable to the current file. Only when the fix is local and you are confident.
- `agent_prompt`: self-contained instruction for another coding agent: file, lines, problem, expected fix, and "verify the issue still exists before changing".
- Secrets: never include the value; quote it masked.

## Re-review (incremental)

- `open_comments` must all be re-checked against the current code, not only the new diff.
- Fixed → `resolved` with a short note ("fixed: now uses a parameterized query"). Code removed / no longer relevant → `dismissed` with reason. Still valid → keep open; update `line_start`/`line_end` if they moved.
- Do not report an open finding again as a new comment.

## Branch content (describes the whole branch, refreshed each review)

- `summary.text`: 2–4 sentences on what the branch does and why (commits, code, user context). `summary.highlights`: typed bullets (`feature`, `fix`, `refactor`, `perf`, `security`, `docs`, `test`, `chore`, `breaking`), at most ~6.
- `walkthrough`: `overview` paragraph + `changes` grouped by area (cohort, files, 1–3 sentence summary). Cover every changed file of the branch; group lockfiles/generated files.
- For incremental reviews, update summary/walkthrough so they still describe the whole branch: start from `context.previous_branch_content` and merge in the new changes. If you only send some of these keys, the others keep their previous value.
- `diagram`: Mermaid `sequenceDiagram` or `flowchart` only when components interact in a non-obvious way. ≤ 12 messages. Avoid `;` and unbalanced quotes in labels. Omit otherwise.
- `effort`: `score` 1–5 (1 trivial ≤5 min, 2 simple ~10, 3 moderate ~20–30, 4 complex ~45–60, 5 very complex >60), `minutes`, one-line `reason`.
- `commit_message`: for the pending changes, following the project convention if a standard defines one (e.g. Conventional Commits), in the project language unless the repo history clearly uses another. Subject ≤ 72 chars, optional body.

## Checks

Report every enabled check from `context.checks` with `pass`, `warn`, `fail` or `n/a` and a short `note` when not `pass`. `hints` are regex leads produced by the script on added lines: confirm or discard each one; they can have false positives (e.g. a legitimate `print` in a CLI) and miss things.

| id | Fail when | Notes |
|---|---|---|
| `debug-code` | Debug output/breakpoints left (console.log, print, debugger, dd…) | Legit logging via the project logger is fine |
| `commented-code` | Blocks of commented-out code added | Explanatory comments are fine |
| `todo-without-ticket` | New TODO/FIXME without a ticket/issue reference | `warn` if the project has no ticket convention |
| `conflict-markers` | `<<<<<<<`, `=======`, `>>>>>>>` left in files | |
| `unwanted-files` | `.env`, keys, binaries, build output, logs, OS files added | `.env.example` is fine |
| `secrets` | API keys, tokens, passwords, private keys | Mask values |
| `personal-data` | Real-looking personal data in logs, fixtures, tests | |
| `new-dependencies` | New dependency unmaintained, incompatible license, or duplicating an existing one | Judge from your knowledge; say when unsure (`warn`) |
| `missing-tests` | New/changed logic without tests | Name the untested case |
| `disabled-tests` | `.only`, `.skip`, `xit`, `@Disabled`… added | |
| `weakened-tests` | Tests deleted or assertions loosened | |
| `change-size` | Too large to review well (rule of thumb > 400 changed lines of logic) | `warn`, suggest splitting |
| `mixed-concerns` | Unrelated changes mixed | Suggest how to split commits |
| `format-noise` | Mass reformatting mixed with logic changes | |
| `breaking-changes` | Public API/contract/schema changed without being intentional/flagged | Add `breaking` highlight when intentional |
| `migrations` | DB migration without a down/rollback path or with unsafe locking | `n/a` if none |
| `undocumented-env` | New env vars not in `.env.example`/docs | |
| `docs-not-updated` | API/config/behavior changes not reflected in docs/README/CHANGELOG | |

Use `n/a` when a check does not apply to the change. Blocking checks that `fail` make the verdict "blocked".

## Large changes

If `diff_lines` is very large (> ~3000), review file by file, prioritise source over generated/lock files (`generated: true`), and say in `note` what was skimmed or skipped.
