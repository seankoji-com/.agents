# Trigger evals: choose-design

Prompts for the manual trigger check described in the new-skill skill.
Run each in a fresh session; record which skill fires.

## Should fire

1. Show me three directions for the new dashboard.
2. We need a redesign of the pricing page; compare options.
3. I can't decide between a sidebar and tabs here.
4. Design the new onboarding screen.
5. Compare interaction patterns for bulk delete.

## Should not fire

1. Change the button colour to blue. (expect: none)
2. Build this page in a bold editorial style. (expect: frontend-design)
3. Review the checkout UI for bugs. (expect: review)
4. Improve this page until the judges score it 9. (expect: hillclimb)
5. Fix the misaligned header on mobile. (expect: none)
