# candidateSearch

Sources candidates for job roles via APIs and AI search, then ranks them for each role.

## Rules and learnings
- Follow every rule in @docs/RULES.md (feature-driven structure, production-grade practices).
- Read @docs/LEARNINGS.md before starting work. Whenever you discover something new and non-obvious about this project (a decision, a provider quirk, a bug cause, a constraint), **append** an entry to `docs/LEARNINGS.md` in its entry format before finishing the task.

## Developer guide
[docs/guide/](docs/guide/README.md) explains the flows, architecture, coding style, decisions and every backend function. When a change alters behaviour described there, update the matching guide page in the same change.

## Team workflow
This project uses three subagents in `.claude/agents/`. For any non-trivial feature, follow this order:

1. **architect**: writes the design and acceptance criteria to `docs/architecture/<feature>.md`.
2. **developer**: implements the design and adds unit tests.
3. **tester**: checks the work against the acceptance criteria and reports PASS/FAIL with bugs.
4. If the tester reports FAIL, send the bugs back to the **developer**, then run the **tester** again. Repeat until it passes.

Small fixes (typos, one-line changes) can skip the architect.
