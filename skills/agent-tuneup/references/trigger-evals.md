# Trigger evals: agent-tuneup

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Why isn't my MCP server connecting?
2. Audit my Claude Code permissions.
3. Codex can't see my skills; fix discovery.
4. Change my agent config so it stops prompting for git status.
5. Troubleshoot why the hooks in my settings don't fire.

## Should not fire

1. Save this decision to project memory. (expect: reremember)
2. Babysit my PR. (expect: babysitter)
3. Set up a GitHub Actions workflow for the tests. (expect: none)
4. Configure the database connection string in my app. (expect: none)
5. File an issue about the flaky login test. (expect: raise-issue)
