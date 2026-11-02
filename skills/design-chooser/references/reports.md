# Design report requirements

## Feature annotations

Give key features and design decisions visible, stable IDs within each option,
such as `A1-F1` and `A1-F2`. The coordinator assigns option prefixes before
dispatch. Pair each marker with a legend entry that names the feature, explains
the decision and its tradeoff, and identifies its location. For existing UI,
say whether it is retained or changed. Mark the requested changes and the
decisions the user can meaningfully compare, rather than every decorative item.

Use small, readable markers beside features without covering content or
intercepting controls. Keep the legend outside the product mockup so report
annotations do not look like proposed product UI. Put the legend directly below
the mockup box in the final frame. Provide text descriptions
alongside colour cues. Keep an ID attached to the same decision through repairs
and feedback; retire removed IDs rather than reassigning them. IDs must be
unique across the presented report. Prefix later rounds, such as `R2-A1-F1`,
so earlier feedback stays unambiguous. Preserve the mapping in the choice record.

## Controls that work in the report host

Keep each option visible in its own frame. Do not put the comparison or its
legends behind report-level tabs. Each option is a self-contained document;
scope its CSS and element IDs so one option cannot affect another.

Distinguish product controls from report controls. Product tabs and other
controls that matter to the comparison need a working demonstration in the
actual presentation host. The coordinator records in the brief whether the
host permits inline JavaScript; unknown support requires the static fallback.
Use native HTML controls where suitable. Use inline
JavaScript only when the host permits it, with local event handlers and no
remote dependencies. A tab must select its matching panel, update selected
state and hide inactive panels. Use accessible tab/panel relationships,
visible focus and keyboard navigation. Avoid global selectors, implicit
element globals and handlers tied to reused IDs.

If the host blocks interaction or the behavior cannot be verified, replace
the affected control with clearly labelled static states or stacked panels.
Expose the content of every relevant state and label the interaction as
unverified. Do not leave a dead tab or button looking usable. Describe the
intended behavior without claiming that a static mockup demonstrates it.

## Check before presenting

Check every option in the actual host at 728px wide and the target viewport
when different. Activate every tab and report control. Verify the matching
content appears, switch away and back, and check keyboard operation. Check
controls again after assembling the final frames, since isolated HTML success
does not prove the embedded report works. A render or screenshot alone does
not verify interaction. Use the static fallback when the host cannot exercise
controls, and state the verification gap.

Check that every visible feature marker has exactly one matching legend entry,
that each entry points to the intended feature, and that markers do not obscure
content or controls. Finish only when each option passes these checks or uses
the labelled static fallback.
