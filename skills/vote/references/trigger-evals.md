# Trigger evals: vote

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. I can't decide between Postgres and SQLite for this service; put it to a vote.
2. We're at a deadlock on the cache design. Poll three models and pick by 2/3.
3. Run a majority vote on whether to keep the feature flag.
4. I'm stuck on how to sequence the launch; let the models vote on it.
5. Break the tie between rewriting the parser and patching it with a three-model vote.

## Should not fire

1. How do I vote in the local election? (expect: none)
2. Pick one of these two dashboard mockups. (expect: choose-design)
3. Think through whether we need a cache here. (expect: think)
4. Challenge my choice between Postgres and SQLite. (expect: challenge)
5. Review this plan for gaps. (expect: review)
