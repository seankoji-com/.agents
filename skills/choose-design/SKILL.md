---
name: choose-design
description: "Compare design options once product decisions are settled. Use for new UI, a requested redesign or an unresolved visual or interaction choice, not for routine edits to an existing design."
---

# Choose a visual design

Use independent mockups to resolve a material UI choice before building. The
coordinator briefs Opus designers, checks their work and presents it for the user
to choose. The designers own the mockups. Invoking this skill requests that
delegation when a material choice remains.

## Size the run

Classify the request before choosing designers. New UI permits exploration;
an explicit redesign permits exploration within its stated boundary. For edits
to existing UI, use the current screen as the baseline. Preserve its visual
identity, content, components and interactions outside the requested change.
A layout, spacing or small feature request alone does not authorise a redesign.
When the existing system determines the edit, implement it directly if requested.
When a material choice remains, compare only alternatives for that choice.
An explicit chooser request keeps this scope. If no choice remains, report that
and implement only if requested; do not invent options.

By default, use Opus for every designer slot whenever a material design choice
needs this skill. Routine changes determined by the existing system need no chooser.
Pick the count from the remaining choice:

- **2** for a new component, or a change the existing system only partly
  constrains.
- **3** for a new screen, page or app, or a redesign with no established system.

A count or explicit model-only roster overrides these defaults. A named model
fills one planned slot; fill the remaining unnamed slots with Opus. A model
mention alone does not increase the count or mean "only this model". For a
single unnamed designer, use Opus. Label an explicitly constrained single-model
run honestly. Do not infer that constraint from a small task or familiar visual
system.

## Write the brief

Read the request and the code before writing. Record the product, the audience,
the screen or component, the real content it shows, its states, the target
platforms and the existing design tokens, components or screenshots. Ask only
about missing intent that would change the design.

A direct invocation, or an authorised workflow selecting this skill, authorises
sending the minimal design brief to the selected roster's providers. That brief
may contain written intent, design tokens, task-relevant non-secret excerpts
and redacted screenshots. User and standing restrictions on providers or content
take precedence. Raw files beyond this brief need explicit sharing scope.
Record this bounded grant and the invoking request as the authority source in
child briefs. Use the sharing-authority procedure in
[T3 dispatch preflight](../agent-tuneup/references/t3-dispatch.md)
for T3 delegates. Carry existing consent into child briefs instead of asking
again for the same authorised context. Prefer a minimal design brief over raw
repository files; host approval and explicit sharing limits still apply.

All designers get the same base brief, including the request type, existing
baseline, allowed changes and what must stay fixed. For existing UI, include
enough visual evidence to preserve it; inspect missing evidence before dispatch
or report the gap. Separate requirements from user preferences. Give each
designer one distinct broad emphasis, such as conventional or distinctive. That
emphasis is the only style direction; it must not resolve the open choice. Leave
the unresolved choice to the designers. Do not show one designer another's work.

## Pick designers

Apply [T3 dispatch preflight](../agent-tuneup/references/t3-dispatch.md) before
selecting T3 routes. Discover the host's delegation capabilities and exact model
identities. Keep any named models and settings. Otherwise choose one compatible
**Opus** route for the batch, applying the preflight's provider score, and use it
at high effort for every unnamed slot. When no Opus route has a score, use the
first compatible route the host lists. A named unavailable or incompatible model
remains a conflict under the preflight; do not substitute for it without the
user's acceptance. A sharing-authority rejection follows the preflight's sharing
procedure, not model substitution to avoid the rejection. A designer that fails
after starting is reported, not replaced. The coordinator may share the model,
because the coordinator does not design. Before dispatch, state the planned
count, exact models and the reason for the count. Check permission and sharing
compatibility for the whole roster. Start compatible authorised designers without
another confirmation. If no compatible Opus route exists before the planned count
is filled, retain partial results and report an incomplete comparison. Do not
substitute another family. The user must explicitly accept a smaller set before
it counts as the completed run.

Label designers A, B, C and so on in dispatch order. In T3 Code, resolve models with
`orchestrator_capabilities` subject to the host's discovery frequency. Start one
`delegate_task` per designer and record each `taskId`. Submit independent launches
together where supported. Follow the returned `next`; if it requires yielding
before all launches, preserve and resume the pending roster. The first launch
or completion does not satisfy the whole roster. Use native delegation elsewhere.
Do not poll, open top-level threads or let a designer start further agents.

A delegated coordinator may start designers only when its assignment permits
children. Otherwise return the brief and planned roster to the parent. Return
all options, HTML, identities and dispatch gaps to the main thread. Only the
main thread presents choices and obtains the user's selection.

## Designer instructions

Within its emphasis, ask each designer for 2 options, or 3 when the brief
supports three distinct directions. For existing UI, vary the requested decision
while keeping the rest of the baseline consistent across options. Do not broaden
the scope to make options look different. For each option, the designer returns:

- A short, memorable name.
- A blurb of two to four sentences giving the intent of the design and why it
  fits the brief.
- One sentence on how it differs from the designer's other options.
- One complete, self-contained HTML document of the main screen. It needs inline
  CSS, no remote fonts, scripts or images, and realistic content in place of
  lorem ipsum. It must render well at 728px wide. If the real target is wider,
  the blurb says how the layout changes there.
- Visible feature IDs and an annotation legend, following
  [report requirements](references/reports.md) for each option. Read these requirements before
  briefing designers and apply them when checking and presenting every option.

Designers must not edit the repository. They return HTML in the final report, or
write it to a task-owned artifact path the coordinator names and report the
path. Designers must not call `html_render` or rely on a child-thread
presentation. A timeout, missing HTML or a bare completion status means no
options came back.

## Check the options

Open every option and check its controls and annotations against the report
requirements and its designer's emphasis. Reject or repair any that breaks the
brief, fails to render, loads remote assets or copies a sibling. For existing UI,
check each change against the allowed scope. Shared baseline elements are expected, not copied
directions. If two designers make the same unresolved choice, ask the later
designer for one redo within the same scope. Do not loop beyond that or invent
a broader redesign to force variety. Report a designer that failed with its
error; do not substitute.

Preserve the design while checking it, except to apply the report's static
fallback and note it in the blurb. Correct inaccurate blurbs.

## Score the options

After checking, send the full set to Neon and Sol in one batch. Each reviews
read-only and independently on four dimensions, with brief strengths and
weaknesses. Read [scoring requirements](references/scoring.md) before dispatch.
Scores inform the choice; they do not replace it.

## Present

In T3 Code, give each option its own frame, grouped by designer. For each,
check the page with `html_preview`, then show it with `html_render` at the
measured height. Each frame opens with a header in the T3 theme variables. The
header holds a label such as `B2 · Opus`, the option name and the blurb.
Below the header, put the mockup in its own box with its own colours, 16px of
padding and `var(--radius)` corners. Title each frame with its label and name.
Show both reviewers' scores and notes.

After the frames, list the labels and names in one line. Ask the user to pick an
option or describe a hybrid using feature IDs, such as "A1-F1 with B2-F3". On hosts
without inline HTML, write each mockup to a task-owned file and give the label,
model, name, blurb and absolute path for each one.

## After the choice

Always wait for the user's choice. Silence or a timeout is not a choice. Record
the chosen option or hybrid and the mockup it came from. Build it only if the
original request asked for implementation, using the project's real stack and
existing components. A further round of options needs a new request.

Stop task-owned delegates when they are done or cancelled. Remove task-owned
mockup files after the choice unless the user wants them kept.
