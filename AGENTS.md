# Agent Guide: Commits

This file tells agents how to create Git commits in this repository.
Read it before you run `git commit`.

## One change per commit

1. Group changes by feature. One commit carries one feature or one fix.
2. Never mix unrelated changes in one commit. Create one commit per feature.
3. Stage only the files that belong to the change. Leave unrelated files
   unstaged.
4. Never commit generated files, editor state, or local configuration. Check
   `.gitignore` first. If a local artifact is not ignored, ask before you add
   a new ignore pattern.

## Commit message

1. Write the subject line in the imperative mood. Say what the commit does:
   "Add a debug panel", not "Added" or "Adds".
2. Keep the subject line under 60 characters. Do not end it with a period.
3. Add exactly one paragraph of description below the subject. Keep it short.
   Three sentences are enough for most changes. Separate the paragraph from
   the subject with one blank line.
4. Write the message in simple English. Use short sentences, active voice,
   and simple tenses. Name the actor. Do not use contractions.
5. Say why the change is needed, then what it does. Do not list every file.
   Do not describe the code line by line.
6. Do not add AI credits, tool names, or "Generated with" footers.

## Message patterns

Use these patterns as a starting point. Change the words, keep the shape.

For a new feature:

```text
Add <feature>

<User needs this because ...>. Add <what you built>. <One sentence about
how it behaves or how it is enabled.>
```

For a bug fix:

```text
Fix <what was broken>

<What happened before, in one sentence.>. <What the cause was.>. <What the
code does now.>.
```

For a dependency or tooling change:

```text
<Update/Replace/Bump> <thing>

<What failed or was outdated.>. <What you changed.>. <One sentence that
says the checks still pass.>
```

## Before you commit

1. Run the checks. The pre-commit hooks run them again, but catch failures
   early:

   ```bash
   uv run pytest
   uv run ruff check .
   uv run ruff format --check
   npm --prefix frontend run build
   ```

2. If a hook fails, fix the problem and commit again. Do not use
   `--no-verify` unless the user asks for it.
3. Do not sign commits. The user signs them later. Run `git commit` with
   `--no-gpg-sign`, and do not use `-S`.
4. Show the user the commit hash and subject after a successful commit.
