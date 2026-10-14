# How the workflows help

Each workflow exists because of a follow-up question you would otherwise ask the
agent after it said it was done. This page names the question and what answers it.

## "Did the tests actually run on this code?"

[imps](plugins/imps.md) records each check with a snapshot of the files it ran
against. If the agent edits anything afterwards, that check goes stale and the report
says so; it can't carry an old pass forward. You get a run ID and a report listing
each requirement, its evidence, and anything still blocked. An interrupted run resumes
from its recorded artifacts and child task handles.

## "What did we decide last session?"

[elephant-goldfish](plugins/elephant-goldfish.md) interviews you and writes the
decisions, constraints, unknowns and acceptance criteria to files. The handoff copies
those files verbatim and records their hashes, so a fresh thread gets exactly the
brief you accepted. It stops there. You decide when implementation starts.

## "Where in their code does it do that?"

[ape](plugins/ape.md) reads another repository against a gap in yours. Each
recommendation cites lines at a resolved commit, names the local files it would
touch, and proposes one small experiment with conditions for keeping or abandoning
it. It never runs the other project's code and never starts editing yours.

## "Why hasn't this PR merged?"

[babysitter](plugins/babysitter.md) checks reviews and CI at the PR's current head,
fixes what you authorized, and asks T3 to wake it on the next failure, comment or
conflict. It keeps one table of every targeted PR and the reason each hasn't merged,
and reports a merge only after GitHub shows one. Branch protection still applies.

## "Which of my agents may run any shell command?"

[agent-tuneup](plugins/agent-tuneup.md) reads the settings files you name and reports
known broad permissions and duplicate rules as codes and locations, without printing
the values. It flags known patterns; it doesn't simulate every permission layer.

## "Would a different model have accepted this?"

[ralph](plugins/ralph.md) has one model implement and a model from another lineage
grade the result. Every piece of feedback, however minor, sends the work back to a
fresh implementation task in the same worktree. It stops at success or at the attempt
limit, and opens a PR only for an accepted change.

## Long jobs stay readable

A multi-stage job keeps its plan, requirements and decisions in one overview in your
thread. Fresh T3 tasks do each stage and return a structured result, so their
exploration and logs stay in files, not in your conversation. A stage counts as done
only when its validator accepts it, and the final check covers every requirement
again. Whether this saves context in practice hasn't been measured; see
[measurement limits](compatibility.md#measurement-limits).

## When to skip all of this

A one-line edit doesn't need saved run state or a second model's review. Ask the agent
directly. Every entry and helper ships as a readable file;
[architecture](architecture.md) explains how they fit together.
