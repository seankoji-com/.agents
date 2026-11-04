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

## Choose dimensions before scoring

Use this default rubric unless the product warrants different dimensions or weights.
Record the scoped user outcome, audience/context and intended emotional response,
such as calm confidence or creative expression. Map these to the dimensions below;
justify each addition, replacement or weight change with a concrete product
requirement or user evidence. Preserve the agreed product scope and identity.
Task value assesses the scoped workflow against the agreed need, rather than
reopening product strategy. Keep the defaults when evidence gives no reason to
change them. Novelty earns credit when it serves the intended experience.

Record the chosen dimensions, weights, product-specific anchors and target before
baseline scoring or edits, and freeze them for the run. Weights must be positive
and sum to 100. These weights are working defaults, not empirically validated
predictors of delight. Model scoring is an evaluation aid, not a validated user
questionnaire or evidence of how the audience actually feels.

| Dimension | Default weight | What the judge must explain with observed evidence |
| --- | --- | --- |
| Task value and audience fit | 15 | Support for the agreed user need, useful outcomes and context of use |
| Clarity and findability | 15 | Information hierarchy, navigation, terminology, instructions and useful content |
| Efficiency and flow | 15 | Unnecessary effort, repetition, interruptions, responsiveness and support for frequent use |
| Control and confidence | 15 | Predictability, feedback, error prevention, undo, recovery, honest claims and transparent consequences/data use |
| Visual craft and coherence | 20 | Typography, spacing, density, colour, imagery, component consistency and supported layouts |
| Emotional appeal and character | 10 | Appropriate personality, pleasure, reassurance, motivation and memorable details |
| Product and brand fit | 10 | Coherence with the agreed identity, audience expectations and intended positioning |

Keep dimension boundaries explicit in the judging brief. Clarity concerns what
users can understand and find; visual craft concerns its visual treatment.
Efficiency concerns effort and flow; control concerns predictability and agency.
Emotional appeal concerns qualities likely to support the intended feeling;
brand fit concerns fidelity to the agreed identity. A judge's own reaction is
not evidence of audience sentiment. Assign each finding a primary dimension;
affect another score only with a distinct observed consequence, explaining why.

## Scoring

Judges assign each dimension an integer from 1 to 10. Define product-specific
examples for every dimension's anchors before scoring, including emotional appeal
and brand fit. Adapt the task-oriented descriptions below to those qualities:

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
Use repository checks plus explicit gates for functional correctness, reliability,
accessibility and performance suited to the actual product. Examples include
completing named tasks, keyboard reachability/focus, assistive-technology use,
measured contrast, zoom/reflow, horizontal overflow, reduced motion, failure
recovery and response-time budgets when relevant. Choose thresholds from the
product's requirements and applicable standards, rather than
inventing a universal performance or accessibility promise.

Record actual outputs, environment, data and revision. A model's visual estimate
of contrast or performance is not a measured result. Scope claims to what the
method can establish; an automated accessibility pass is not complete accessibility
verification. Record baseline failures instead of silently exempting them.
Perceived confidence also does not establish actual security or privacy protection;
retain any required technical checks separately.

Coverage includes the named flows at supported sizes and relevant loading, empty,
error and recovery states. Every judge must perform the required interactions on
the actual candidate and provide action/results evidence. Missing required checks,
unviewed states or inaccessible UI prevent goal acceptance even when scores pass.

## Research basis and limits

These dimensions synthesize complementary frameworks rather than reproduce a
validated instrument. [Norman's emotional design](https://jnd.org/emotional-design-people-and-things/)
and [NN/g's pillars of delight](https://www.nngroup.com/articles/pillars-user-delight/)
cover appearance, use and personal meaning. [Nielsen's heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/)
inform control, prevention, recovery and efficiency. [Morville's honeycomb](https://semanticstudios.com/user_experience_design/)
includes usefulness and credibility; [UEQ+](https://ueqplus.ueq-research.org/)
supports selecting qualities for the product and research question.
[W3C guidance](https://www.w3.org/WAI/fundamentals/accessibility-usability-inclusion/)
combines accessibility standards with evaluation involving people with disabilities.
Use available research with the intended audience to inform anchors and report
actual user outcomes separately. Without that evidence, user delight remains
unverified even when the design evaluation passes.
