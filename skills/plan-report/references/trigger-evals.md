# Trigger evals: plan-report

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Show the plan on a timeline.
2. Give me a progress report chart.
3. Show the final calibration for this run.
4. Render the ship plan as a Gantt chart.
5. Where are we on the timeline?

## Should not fire

1. Catch me up on this chat. (expect: none)
2. Make a bar chart of monthly sales. (expect: none)
3. Write a project plan document. (expect: none)
4. Ship this. (expect: ship)
5. Summarise the test timings. (expect: test-writer)
