## Tooling Rules
- ALWAYS use `bun` instead of `npm` or `yarn` for TypeScript/JavaScript
- ALWAYS use `bunx` instead of `npx`
- ALWAYS use `uv` for Python package management and virtual environments
- For iOS, use `swift build` and `swift test`

## File Conventions
- CLAUDE.md belongs in the repo root, not in subdirectories
- All new features must include tests in the appropriate test directory

## Post-Implementation Checklist (MANDATORY after every feature)
1. Run the full test suite and fix all failures
2. Update TODO.md to mark completed items and add any new items discovered
3. Update README.md if new features affect the public API or setup
4. Provide a conventional commit message (feat:, fix:, docs:, etc.)
5. Never stage all files — only stage files related to the current task

## Git Rules
- Only `git add` files that were modified in the current task
- Never force push
- Use separate commits for logically distinct changes when asked

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
