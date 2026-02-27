# Claude

Claude-specific instructions. Read AGENTS.md first.

## Task Handoff
- Read `.context/progress.md` before starting work
- After completing a task, update `.context/progress.md` with what changed
- Delete `.context/next-task.md` when task is complete

## Code Style
- No hardcoded KB-specific references in backend logic
- Use os.getenv() for all secrets and configurable values
- Functions extracted into modules by concern (see AGENTS.md architecture)
- Fail-open on external API errors (return safe defaults)

## Eval Discipline
- Run eval after any backend change: `python evals/eval_loomo.py`
- Must maintain 54/58 (93.1%) or above
- If eval drops, fix before committing
