# acanimal-code-review

A local, CodeRabbit-style code reviewer packaged as an [Agent Skill](https://agentskills.io) (`SKILL.md`). Works with Claude Code, OpenCode, Cursor and other agents that support skills.

- Reviews what you are about to commit (staged, unstaged and new files), whenever you ask.
- Incremental re-reviews: verifies previous comments and only reviews what changed since.
- Learns your project's standards (from configs/docs and from the code), applies them, and lets them evolve with exceptions, deprecations and migrations.
- Verdict ("ready to commit" / "N blockers"), summary, walkthrough, diagram, effort, checks, proposed commit message, comments with suggested diffs and agent prompts.
- Keeps the whole history in the repo (`.code-review/`) and a project-wide HTML panel with every branch and insights. Open `.code-review/index.html` with a double click.

Read-only by design: it never runs your tools, never commits, never touches your index/stash, and only edits code after you confirm.

## Requirements

`git` and `python3` (3.9+, standard library only). On macOS both come with the Xcode Command Line Tools.

## Install

```bash
npx skills add <owner>/acr-code-review        # into the current project
npx skills add <owner>/acr-code-review -g     # globally, for all projects
npx skills update                            # later
```

Choose symlink or copy and the agents when prompted. Manual install: copy `skills/acr-code-review/` into `.claude/skills/` (read by Claude Code, OpenCode and Cursor) or any skills folder of your agent.

## Use

Ask your agent, in any language:

- "review my changes" · "full review" · "review the whole branch"
- "explain ACR-1a2b3c" · "fix the blockers" · "dismiss ACR-1a2b3c, it is intentional"
- "analyze the project standards" · "show pending standards" · "STD-4f2a doesn't apply to src/legacy until March"
- "open the review panel"

Commit the `.code-review/` folder together with your code. Generated content is in English by default; change it per project ("set the review language to Spanish").

## What gets written to your repo

```
.code-review/
├── index.html            # static viewer (does not change between reviews)
├── .gitattributes        # data/index.js merges with the union driver
├── .gitignore            # .tmp/ (local, per worktree)
└── data/
    ├── config.js         # language, base branch, checks
    ├── index.js          # list of data files for the viewer
    ├── branches/*.js     # one file per branch: runs, comments, summary…
    ├── standards/*.js    # one file per standard
    └── standards-log/*.js# one file per standards change
```

Each branch sees the history of its base plus its own; other branches appear after they are merged.

## License

MIT, see [LICENSE](LICENSE).
