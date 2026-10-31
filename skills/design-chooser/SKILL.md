---
name: design-chooser
description: Use before building or changing anything that needs a visual design decision, such as a screen, page, component, layout, colour, type or restyle. Gets mockup options from one to three model lineages and has the user choose before building.
---

# Choose a visual design

Use this skill whenever a build needs a visual decision. Mockups come from
independent designers in different model lineages. The user chooses before
anything is built. The coordinator writes the brief, checks the mockups and
presents them. It does not design.

## Size the run

Pick how many designers to use from the scope of the change:

- **1** for a change inside an existing visual system, such as restyling a
  control or adjusting spacing.
- **2** for a new component, or a change the existing system only partly
  constrains.
- **3** for a new screen, page or app, or a redesign with no established system.

A count or model the user names overrides this table. Before dispatch, state the
count and the reason in one line. Do not wait for confirmation.

## Write the brief

Read the request and the code before writing. Record the product, the audience,
the screen or component, the real content it shows, its states, the target
platforms and the existing design tokens, components or screenshots. Ask only
about missing intent that would change the design. Share repository content with
another provider only where host permissions and sharing limits allow it.

All designers get the same brief. Do not suggest a direction or style, and do not
show one designer another's work.

## Pick designers

Discover the host's delegation capabilities and exact model identities. Keep any
named models and settings. Otherwise go through this order and take the first
available models, one per lineage: **Sol, Opus, Wonder Full, Argon, Grok 4.7**.
Two aliases, versions or effort settings of the same model are one lineage. The
coordinator's own lineage is eligible, because the coordinator does not design.
If fewer lineages are available than the run needs, use the ones you have and
report the gap. Never fill a slot with a second model from a lineage already in
use.

Label designers A, B and C in dispatch order. In T3 Code, resolve models with
`orchestrator_capabilities`, start one `delegate_task` per designer, record each
`taskId` and follow the returned `next`. Use native delegation elsewhere. Do not
poll, open top-level threads or let a designer start further agents.

## Designer instructions

Ask each designer for 2 options, or 3 when the brief supports three distinct
directions. For each option, the designer returns:

- A short, memorable name.
- A blurb of two to four sentences giving the intent of the design and why it
  fits the brief.
- One sentence on how it differs from the designer's other options.
- One complete, self-contained HTML document of the main screen. It needs inline
  CSS, no external fonts, scripts or images, and realistic content in place of
  lorem ipsum. It must render well at 728px wide. If the real target is wider,
  the blurb says how the layout changes there.

Designers must not edit the repository. They return HTML in the final report, or
write it to a task-owned artifact path the coordinator names and report the
path. Designers must not call `html_render` or rely on a child-thread
presentation. A timeout, missing HTML or a bare completion status means no
options came back.

## Check the options

Open every option. Reject or repair any that breaks the brief, fails to render,
loads remote assets or copies a sibling. If two designers return
near-identical directions, ask the later designer for one redo with the same
brief and a note to avoid that direction. Do not loop beyond that. Report a
designer that failed with its error; do not substitute.

Do not change a design's look while checking it. Correct a blurb only where it
misstates the mockup or the brief.

## Present

In T3 Code, give each option its own frame, grouped by designer. For each,
check the page with `html_preview`, then show it with `html_render` at the
measured height. Each frame opens with a header in the T3 theme variables. The
header holds a label such as `B2 · Grok 4.7`, the option name and the blurb.
Below the header, put the mockup in its own box with its own colours, 16px of
padding and `var(--radius)` corners. Title each frame with its label and name.

After the frames, list the labels and names in one line. Ask the user to pick an
option or describe a hybrid, such as "A1's layout with C2's type". On hosts
without inline HTML, write each mockup to a task-owned file and give the label,
model, name, blurb and absolute path for each one.

## After the choice

Always wait for the user's choice. Silence or a timeout is not a choice. Record
the chosen option or hybrid and the mockup it came from. Build it only if the
original request asked for implementation, using the project's real stack and
existing components. A further round of options needs a new request.

Stop task-owned delegates when they are done or cancelled. Remove task-owned
mockup files after the choice unless the user wants them kept.
