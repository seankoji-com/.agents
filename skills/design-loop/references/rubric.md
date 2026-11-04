# Fix the evaluation contract

Use observed examples as quality anchors and measurable checks as separate gates.
Do not describe a model score as an objective measurement. Agreement across model
families still does not establish human preference or production usability.

## Reference anchors

Research a small set of leading products comparable in audience, task and platform.
Record why each qualifies, the source URL, capture date, observed flow/state and
viewport. Capture relevant interactions as well as polished landing screens.
Keep reference images in the local report; cite source URLs in the PR. Upload
third-party captures only when sharing authority covers them.

Capture the product baseline under comparable conditions with synthetic or redacted
data. Label differences that prevent direct comparison. An inaccessible reference
or state remains a gap; it cannot anchor a claim about unobserved behavior.

## Scoring

Use this default rubric unless the product warrants different dimensions or weights.
Record the chosen dimensions, weights, anchors and target before edits, and freeze
them for the run. Weights must be positive and sum to 100.

| Dimension | Default weight | What the judge must explain with observed evidence |
| --- | --- | --- |
| Hierarchy | 20 | Primary task, information order, emphasis and scan paths |
| Typography | 15 | Readability, hierarchy, line lengths and label treatment |
| Spacing and density | 15 | Grouping, alignment and useful information at supported sizes |
| Consistency | 15 | Components, tokens and behavior across the scoped states |
| Interaction clarity | 25 | Discoverability, feedback, navigation and recovery in real tasks |
| Product and brand fit | 10 | Suitability for the audience and agreed identity |

Judges assign each dimension an integer from 1 to 10. Define product-specific
examples for the anchors before scoring:

| Score | Anchor |
| --- | --- |
| 1–2 | The dimension substantially obstructs the scoped tasks |
| 3–4 | Repeated problems make comprehension or interaction difficult |
| 5–6 | Usable baseline with visible inconsistencies or friction |
| 7–8 | Clear and coherent, with specific remaining shortcomings |
| 9 | Comparable to the chosen leading examples for the scoped tasks |
| 10 | Meets the strongest anchors throughout the required states, with no observed shortcoming in this dimension |

Explain intermediate scores with the nearest anchors. The coordinator calculates
the weighted overall score out of 10, not a judge's separate overall impression.
Default precision is one decimal place: sum each integer score times its integer
percentage weight, divide by 100, and round half up to one decimal. Record another
precision only at setup. Apply the same arithmetic to target comparisons and
progress. For example, weighted sum 845 gives 8.5. Retain dimension scores and the
unrounded sum to make the calculation auditable. A missing dimension means an
incomplete evaluation, not zero or a reweighted average.

The operator chooses the target. Do not lower it, change weights or replace a
strict judge merely to obtain a pass. No individual score cancels a confirmed bug.

## Measurable checks and coverage

At setup list each required check, method, threshold, scoped states and evidence.
Use repository checks plus checks suited to the actual product. Examples include
completing named tasks, keyboard reachability/focus, measured contrast, horizontal
overflow at supported widths and response-time budgets when relevant. Choose
thresholds from the product's requirements and applicable standards, rather than
inventing a universal performance or accessibility promise.

Record actual outputs, environment, data and revision. A model's visual estimate
of contrast or performance is not a measured result. Scope claims to what the
method can establish; an automated accessibility pass is not complete accessibility
verification. Record baseline failures instead of silently exempting them.

Coverage includes the named flows at supported sizes and relevant loading, empty,
error and recovery states. Every judge must perform the required interactions on
the actual candidate and provide action/results evidence. Missing required checks,
unviewed states or inaccessible UI prevent goal acceptance even when scores pass.
