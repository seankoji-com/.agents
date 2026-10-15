# Resolve an imps request

When the command has no request, ask which operation to run. Do not assume `doctor`.
Each workflow manifest declares the short picker list and anchored routes for free
text. Apply those routes to the whole request in order. The first matching route wins.
If no route matches, ask the user to choose from the picker. For example, `pr/foo`
matches both the PR and repository patterns; the earlier PR route wins.

For imps, a task without an operation uses `run`. Write the text after the skill mention as
`{"text": "the full request"}` to a scratch JSON file, then run
`python3 PKG/scripts/input.py --input FILE`. Check `ok`. The helper classifies input
without running commands or contacting GitHub. Use its operation and arguments:
It also accepts a full request with a leading `$t3-imps`, `/t3-imps`, or `t3-imps`.
Put the mention before the request. Operation names are reserved first words:
write `run status page shows stale data` or `run audit trail lacks timestamps`
when those words begin a free-text task. Use `checklist PATH` with a readable file;
the path is required. The short discussion form is lowercase `discussion N`.

An empty request or a bare imps mention returns `operation: null`, empty `arguments`,
the `personas` flag, and `picker: true`. A bare `run` returns `needsArgument: true`;
ask for the task before continuing. Keep all other input classification unchanged.

| Input | Operation |
| --- | --- |
| Free-text task | `run` |
| Issue numbers, such as `42 #43` | `issues` |
| GitHub Discussion URL or `discussion N` | `discussion` |
| Existing Markdown checklist path, including spaces | `checklist` |
| `imp-agency`, `issue-mode`, `/imps:imps` | `audit`, `issues`, `run` |

Explicit `run` still detects issue, discussion, and checklist input. A nonexistent
bare path remains task text; explicit `checklist PATH` fails if it cannot be read.
These aliases translate requests after the entry loads. They are not registered
Claude colon commands in T3.

If `personas` is true, load `PKG/references/personas.md` and add its required
acceptance obligation before initializing the plan. For an explicit `doctor`
request, load only the doctor workflow and report its checks.
For `issues`, `audit`, or `blast-radius`, load the corresponding entry playbook.
For `prs`, load the installed babysitter entry as directed by the imps entry.
