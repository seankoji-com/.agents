# Trigger evals: reremember

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. That memory about the port is wrong; the code uses 8080 now. Correct it.
2. Consolidate what the project remembers about the deploy process.
3. We just settled that reviewers come from another model family; record it for later sessions.
4. The remembered cache TTL contradicts the config file.
5. Clean up the duplicated project memories.

## Should not fire

1. Remind me to buy milk. (expect: none)
2. Close out this thread. (expect: settle)
3. Fix my agent permissions. (expect: agent-tuneup)
4. Write this up as a GitHub issue. (expect: raise-issue)
5. Summarise what changed in this chat. (expect: none)
