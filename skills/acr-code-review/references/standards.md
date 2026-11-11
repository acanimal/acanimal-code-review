# Project standards

The catalog of how this project writes code. It lives in `.code-review/data/standards/` (one file per standard) with a changelog in `.code-review/data/standards-log/`. Both are committed.

## Lifecycle

| Status | Meaning | Enforced in reviews |
|---|---|---|
| `proposed` | Inferred or suggested, waiting for the user's validation | no |
| `active` | Validated / explicit | yes, on new and changed code |
| `deprecated` | Old pattern being migrated away from (`replaced_by`) | only blocks *new* uses |
| `rejected` | User said no; kept for history | no |

Origins: `explicit` (written in a config or doc), `inferred` (deduced from the code), `user` (stated by the user).

Levels → comment severity: `required` → major (blocks commit), `recommended` → minor, `preference` → nitpick.

## Initial analysis (and re-analysis)

1. `CRR repo-stats`. Tell the user the size and `suggested_scope`, and ask:
   - `full` (≤ ~400 source files): analyze everything.
   - `sample`: analyze `sample_files` (a spread across folders) plus anything the user points at.
   - `on-demand`: analyze only the areas the user names now; others later ("analyze standards in src/api").
   Re-analysis can be limited to a folder.
2. **Explicit sources** (`explicit_sources`): read each (linter/formatter configs, tsconfig, editorconfig, commitlint, package.json scripts/engines, CONTRIBUTING, AGENTS.md, CLAUDE.md, cursor rules, PR templates, architecture docs). Turn the rules that matter for review into standards with `origin: explicit`, `status: active`, and `source.file` + `source.detail`. Skip purely mechanical rules a formatter enforces automatically unless the user wants them reviewed. Group related low-level lint rules into one meaningful standard rather than one per rule.
3. **Implicit patterns**: read the code in scope and infer conventions, each with evidence (`examples`) and `prevalence`. Cover all kinds:
   - naming (files, functions, components, tests), folder/module structure, layering and dependencies between layers
   - error handling, logging, validation, configuration and env access
   - data access, API/HTTP clients, state management, async patterns
   - testing (framework, location, naming, fixtures/mocks), test coverage habits
   - libraries (which one is used for X), security practices, documentation, git/commit conventions (from `git log`)
   Record them as `origin: inferred`, `status: proposed`. Only propose patterns that are consistent (e.g. ≥ ~70% of relevant cases) and useful for review.
4. **Competing patterns** (two ways of doing the same thing): do not pick one. Ask the user which is the standard. If the answer is "new code uses A, old code uses B", record A as active and B as deprecated with `replaced_by` = A and measure the remaining usages of B (`record_migration`).
5. Record everything in one `CRR std` call, then present the proposals to the user grouped by category, short, and ask them to validate (all, some, adjust or reject). Apply their answers with `activate` / `update` / `reject`.
6. On re-analysis: also detect standards the code no longer follows, update `record_migration` counts for deprecated standards, and propose changes instead of applying them.

Keep descriptions short and actionable: the rule, why, a one-line good/bad example.

## Evolving the catalog

Sources of change, all of them require the user's agreement:
- **Review feedback**: a dismissed comment whose reason is a general rule → ask "turn this into a standard?" A comment the user says is fine only in some place → exception.
- **New patterns** noticed in reviews (`suggestions`) → ask whether to record them.
- **Direct instruction** ("from now on DTOs live in /dto") → propose the standard text, apply after OK (`origin: user`, `status: active`).
- **Drift alerts** from `context.alerts.drift` (repeated violations or dismissals of the same standard) → ask whether the standard still reflects reality; offer re-analysis.

## Divergence from the original source

When an `explicit` standard is changed here, the source file (e.g. `.eslintrc`, CONTRIBUTING.md) now disagrees. Always:
1. Propose the concrete edit to the source file and ask for confirmation.
2. If accepted: edit it and send the update with `"source_updated": true` (or `resolve_divergence` afterwards).
3. If not: the standard stays flagged `divergent`; it appears in `alerts` on every review until synchronized.

Never edit a source file without confirmation.

## Exceptions

- Per file or directory (glob allowed). A reason is mandatory; `expires` (YYYY-MM-DD) is optional.
- While active, the standard is not enforced on those paths (`excepted_files` in context).
- When expired it stops applying and is reported in `alerts` on every review: ask the user to renew (new `add_exception` with a new date) or remove it.

## Conflicts between branches

Each standard is its own file, so different standards changed in parallel merge cleanly. If two branches change the same standard, git reports a conflict in that file; the user resolves it manually. The script refuses to run while a data file has conflict markers and names the file.
