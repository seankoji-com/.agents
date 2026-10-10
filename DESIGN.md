# DESIGN.md

## 1. Aesthetic north star & archetype

### Direction: the workflow workbench

**Change the model. Keep the workflow.**

t3-plugins packages repeatable development workflows as readable instructions, deterministic local tools, and T3-owned orchestration. The website must make that division understandable, get a developer to a first result, and leave the engineering details within reach.

The visual reference is an oversized technical manual laid across a working desk: ink, warm paper, acid-yellow tabs, numbered procedures, large diagrams, and actual execution footage.

Use the project's unusual plugin names for personality. Give each one a small, diagrammatic line illustration. An elephant remembering a brief and a goldfish carrying the handoff can be funny without turning the documentation into a mascot parade.

### Scope and precedence

This document governs the documentation website and its reusable visual components.

The current site uses MkDocs Material, Markdown, and `docs/stylesheets/extra.css`. Implement within that stack. Do not introduce a frontend framework, Tailwind dependency, application backend, or replacement documentation engine solely to achieve this design.

- Author content in `docs/`.
- Keep shared styling in `docs/stylesheets/extra.css`.
- Store illustrations and recorded demonstrations in `docs/assets/`.
- Use theme overrides when structural changes require them.
- Never edit generated `site/` or `dist/`.
- This specification supersedes existing visual styling, including teal accents, system-font typography, and rounded promotional cards.
- Product behavior, commands, ownership rules, and compatibility claims remain governed by their implementation and technical documentation.

### The developer experience is the hero

The homepage must answer these questions in order:

1. What carries over when I change providers?
2. What do I run?
3. What observable result do I get?
4. Which plugin fits my next task?
5. What are the limits?

Use this exact hero structure:

| Element | Content or constraint |
|---|---|
| Eyebrow | `WORKFLOWS FOR T3 CODE` |
| Headline | `Change the model.` / `Keep the workflow.` |
| Supporting copy | “Plan, research, implement, and check your work with readable instructions and local tools. T3 owns delegation and watches.” |
| Primary action | `Install t3-plugins` |
| Secondary action | `Watch the first check` |
| Technical link | `Read the architecture` |
| Adjacent proof | Complete installation commands and the instruction to paste the generated prompt into T3 |

The installation block must preserve the documented sequence:

```sh
brew install seankoji-com/tap/t3-plugins
t3-plugins install
t3-plugins doctor
t3-plugins prompt imps doctor
```

Keep this instruction directly beneath it:

> Paste the printed prompt into a T3 thread attached to your repository.

Show prerequisites beside the commands: T3 Code, a working provider, and execution-host access. Link to the source-installation path. Do not make users hunt through a video for commands.

### Prove the path to value

Use one real recording showing installation, local doctor output, prompt generation, and the T3 readiness report. A reported missing capability is a legitimate result.

- Show the package version, recording date, execution environment, and prerequisites.
- Measure installation and the T3 readiness check separately.
- Installation timing begins when the first command executes and ends when prompt generation completes.
- Readiness timing begins when the prompt is submitted to T3 and ends when the report appears.
- Identify warm caches and already-installed dependencies.
- Label cuts and playback acceleration.
- Publish elapsed-time claims only after recording and measuring them.
- Until then, use `See the installation steps`. Never invent a “30-second setup” promise.
- Separate deterministic local checks from live-provider compatibility.

The next demonstration may show an imps change and its revision-bound verification. Its caption must distinguish implementation, local tests, review, merge, and deployment.

### Homepage composition

Use this sequence:

1. **Hero and executable instructions.**
2. **Full-bleed demonstration:** actual terminal and T3 footage with a readable poster and transcript.
3. **Choose a job:** seven numbered rows, each pairing an outcome with its plugin.
4. **Architecture diagram:** instructions → local helpers or T3 tools; show the shared state core specifically on the imps path.
5. **Evidence and limits:** current compatibility information and links to testing.
6. **Final installation link:** a short return to the next action.

The plugin index is an ordered workbench, not a wall of interchangeable cards. Each row contains a two-digit index, outcome, plugin name, one-sentence explanation, and one explicit link.

Engineering details belong in linked guides and native disclosure elements. Keep prerequisites, failures, compatibility limits, and the next action visible.

### Image and motion direction

Full-bleed means a surface or media band spans the available page width; readable text remains inside its container.

- Use actual interface captures, technical illustrations, and readable diagrams.
- Desktop demonstration aspect ratio: `16 / 9`.
- Mobile poster aspect ratio: `4 / 3`, using a purpose-made crop.
- Playback must expose the complete recording without cropping terminal output.
- No stock photographs, abstract gradient orbs, fake terminal output, floating glass panels, or decorative provider-logo clouds.
- No text embedded in a hero image.
- No scroll hijacking, cursor followers, or continuous background motion.
- A static page must communicate the complete product story.

### Writing rules

Write in terms of actions and artifacts: generate a prompt, inspect a receipt, resume a run, check a revision.

Ban “supercharge,” “unlock,” “seamless,” “revolutionary,” “AI-powered productivity,” and unsupported efficiency multipliers.

Use sentence case. Preserve exact plugin names and command spelling. Do not imply that unit tests prove provider behavior.

---

## 2. Typography system

### Font families

| Role | Family | Weights | Usage |
|---|---|---|---|
| Display | [Space Grotesk](https://fonts.google.com/specimen/Space+Grotesk) | 500, 600, 700 | Hero, page titles, section headings |
| UI/body | [Instrument Sans](https://fonts.google.com/specimen/Instrument+Sans) | 400, 500, 600, 700 | Prose, controls, navigation |
| Mono | [IBM Plex Mono](https://fonts.google.com/specimen/IBM+Plex+Mono) | 400, 500, 600 | Commands, labels, measurements, identifiers |

CDN reference for prototypes only:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link
  href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap"
  rel="stylesheet"
>
```

Production must self-host these families with `font-display: swap`. When implementing the site, commit the exact WOFF2 files and their license texts under `docs/assets/fonts/`. Record each file's family, weight range, upstream release or commit, source URL, and SHA-256 checksum in `docs/assets/fonts/manifest.json`. Record subset settings and the resulting file checksum when subsetting. Font updates must change this manifest and pass visual verification in the same PR. Do not fetch mutable font assets during builds or load the CDN stylesheet in production. The CDN example is not a version pin. Do not load both self-hosted and CDN copies.

```css
:root {
  --font-display: "Space Grotesk", "Arial", sans-serif;
  --font-body: "Instrument Sans", "Segoe UI", sans-serif;
  --font-mono: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace;
}
```

### Type scale

Values assume the browser's default `1rem = 16px`. Set `html` to `font-size: 100%`; do not override the user's default font size.

| Role | Size below 48rem | Size at 48rem+ | Weight | Tracking | Line-height |
|---|---:|---:|---:|---:|---:|
| Display | `3rem` | `clamp(3.5rem, 5.2vw, 5.5rem)` | 700 | `-0.055em` | `1.02` |
| H1 | `2.5rem` | `3.5rem` | 700 | `-0.04em` | `1.08` |
| H2 | `2rem` | `2.75rem` | 600 | `-0.035em` | `1.12` |
| H3 | `1.375rem` | `1.625rem` | 600 | `-0.02em` | `1.25` |
| Lead | `1.125rem` | `1.25rem` | 400 | `-0.01em` | `1.5` |
| Body | `1rem` | `1rem` | 400 | `0` | `1.625` |
| UI/control | `0.875rem` | `0.875rem` | 600 | `0` | `1.25` |
| Code | `0.875rem` | `0.875rem` | 400 | `0` | `1.6` |
| Label | `0.6875rem` | `0.6875rem` | 500 | `0.10em` | `1.45` |
| Micro-copy | `0.75rem` | `0.75rem` | 400 | `0.01em` | `1.5` |

### Enforcement

- Display, H1, H2, and H3 use the display family.
- Uppercase labels always use mono, `0.6875rem`, weight `500`, and `0.10em` tracking.
- Commands preserve case and use zero tracking.
- Body measure: `65ch` maximum. Lead measure: `44ch`. Hero headline measure: `18ch`.
- Body paragraphs have `1rem` bottom spacing.
- Article H2 spacing: `3rem` above and `1rem` below.
- Article H3 spacing: `2rem` above and `0.75rem` below.
- No justified text or manual line breaks in body copy.
- Hero line breaks may be editorial at desktop widths; remove forced breaks below `30rem`.
- Use tabular numerals for durations, versions, and evidence tables.
- Micro-copy is for supplementary metadata. Errors and instructions remain at least `0.875rem`.
- Keep MkDocs' body and code font variables mapped to these families. Explicitly override Material's typeset sizing so its defaults do not shrink the specified rem scale.

---

## 3. Colour palette & design tokens

### Palette: warm paper, green ink, acid yellow

Use warm, olive-tinted surfaces and green-tinted dark surfaces. Acid yellow marks the next action.

Default to the operating-system preference on first visit. Persist an explicit user choice. Support both `.dark` and MkDocs Material's existing dark-scheme attribute.

All authored colours must come from these tokens. Do not use Tailwind slate, zinc, neutral, or un-tinted gray palettes.

```css
:root {
  color-scheme: light;

  --surface-primary: hsl(60 20% 96%);
  --surface-secondary: hsl(60 18% 91%);
  --surface-recessed: hsl(65 15% 85%);

  --border-subtle: hsl(70 10% 74%);
  --border-strong: hsl(90 8% 43%);

  --text-high: hsl(150 20% 10%);
  --text-muted: hsl(140 10% 33%);

  --accent: hsl(68 95% 55%);
  --accent-hover: hsl(68 95% 62%);
  --accent-pressed: hsl(68 85% 47%);
  --on-accent: hsl(150 20% 10%);

  --success: hsl(150 65% 25%);
  --success-surface: hsl(145 30% 90%);
  --warning: hsl(32 90% 27%);
  --warning-surface: hsl(43 65% 90%);
  --error: hsl(4 65% 36%);
  --error-surface: hsl(5 45% 93%);

  --focus-ring: hsl(150 20% 10%);
  --selection-bg: hsl(68 95% 55%);
  --selection-text: hsl(150 20% 10%);
  --overlay: hsl(150 20% 8% / 0.72);

  --terminal-bg: hsl(150 20% 10%);
  --terminal-text: hsl(60 20% 96%);
  --terminal-muted: hsl(75 12% 72%);
  --terminal-border: hsl(140 9% 48%);

  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.25rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-10: 2.5rem;
  --space-12: 3rem;
  --space-16: 4rem;
  --space-20: 5rem;
  --space-24: 6rem;

  --radius-control: 0.25rem;
  --radius-panel: 0.5rem;
  --radius-pill: 999px;

  --duration-press: 80ms;
  --duration-fast: 120ms;
  --duration-ui: 180ms;
  --duration-reveal: 420ms;
  --ease-ui: cubic-bezier(0.2, 0, 0, 1);
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);

  --shadow-floating: 0 0.5rem 1.5rem hsl(150 20% 8% / 0.14);

  --z-header: 20;
  --z-menu: 30;
  --z-dialog: 40;
  --z-toast: 50;
}

.dark,
[data-md-color-scheme="slate"] {
  color-scheme: dark;

  --surface-primary: hsl(150 20% 10%);
  --surface-secondary: hsl(150 16% 14%);
  --surface-recessed: hsl(150 22% 7%);

  --border-subtle: hsl(140 10% 27%);
  --border-strong: hsl(90 8% 53%);

  --text-high: hsl(60 20% 96%);
  --text-muted: hsl(75 12% 72%);

  --accent: hsl(68 95% 55%);
  --accent-hover: hsl(68 95% 62%);
  --accent-pressed: hsl(68 85% 47%);
  --on-accent: hsl(150 20% 10%);

  --success: hsl(150 55% 68%);
  --success-surface: hsl(150 30% 15%);
  --warning: hsl(43 85% 67%);
  --warning-surface: hsl(35 35% 15%);
  --error: hsl(4 80% 75%);
  --error-surface: hsl(4 30% 16%);

  --focus-ring: hsl(68 95% 55%);
  --selection-bg: hsl(68 95% 55%);
  --selection-text: hsl(150 20% 10%);
  --overlay: hsl(150 20% 4% / 0.80);

  --shadow-floating: 0 0.5rem 1.5rem hsl(150 20% 4% / 0.40);
}
```

### Colour rules

- Primary surface covers the page; secondary groups related content; recessed holds code and inset data.
- The four `--terminal-*` tokens are intentionally theme-invariant. Both themes inherit their exact `:root` values, keeping a dark terminal surface with light text. Apply the contrast checks to that same palette in both themes.
- Subtle borders separate noninteractive regions. Strong borders identify controls and interactive boundaries.
- Acid yellow is a filled background or graphic marker. Never use it as small text on a light surface.
- Accent-filled controls always use `--on-accent`.
- Body links use `--text-high`, a `1px` underline, and `0.18em` underline offset. Hover increases underline thickness to `2px`.
- Status text uses its semantic foreground over its corresponding semantic surface.
- Every status includes text and an icon. Colour alone never communicates success or failure.
- No gradients, translucent reading surfaces, glow, or backdrop blur.
- Verify rendered contrast: `4.5:1` for normal text, `3:1` for large text and required control boundaries. These are release gates, including hover, focus, and error states.
- Map Material's background, foreground, code, link, and search tokens to this system. Its built-in dark-scheme name `slate` is an integration identifier, not permission to use a slate palette.

---

## 4. Spatial geometry & layout engine

### Grid and density

Base unit: `0.25rem`, equivalent to `4px` at the default font size.

Use only the spacing tokens above, except for borders, icon strokes, and specified optical corrections.

| Context | Required spacing |
|---|---|
| Compact metadata group | `0.5rem` gap |
| Control icon to label | `0.5rem` |
| Related controls | `0.75rem` |
| Panel padding | `1.5rem`; `1rem` below 48rem |
| Documentation section | `3rem` vertical separation |
| Homepage section | `6rem` vertical padding; `3rem` below 48rem |
| Hero | `5rem` top and `4rem` bottom; `2.5rem` / `2rem` below 48rem |
| Plugin row | `1.5rem` vertical padding; `1.25rem` below 48rem |

### Containers and breakpoints

- Small: below `48rem`.
- Medium: `48rem` through `74.999rem`.
- Large: `75rem` and above.
- Outer gutter: `1rem` small, `2rem` medium, `3rem` large.
- Marketing container: `88rem` maximum, including inline padding.
- Documentation shell: `94rem` maximum, including inline padding.
- All grid children use `min-width: 0`.
- Use `box-sizing: border-box` globally.

The hero uses a 12-column grid with `1.5rem` gaps at large widths:

- Headline and copy: 7 columns.
- Installation panel: 5 columns.
- Align both regions to their top edge.
- Below `75rem`, stack copy above commands with a `2rem` gap.

Documentation at large widths uses:

- Navigation: `15rem`.
- Article: `minmax(0, 1fr)`, with prose capped at `65ch`.
- In-page contents: `12rem`.
- Column gaps: `2rem`.

Hide the contents rail below `75rem`. Move navigation into an accessible drawer below `48rem`.

### Structural grammar

Use horizontal rules to create chapters.

- Major chapter boundary: `2px solid var(--text-high)`.
- Row separator: `1px solid var(--border-subtle)`.
- Interactive outline: `1px solid var(--border-strong)`.
- Chapter index: mono, `0.75rem`, muted, in a `2.5rem` column.
- Plugin rows at large widths: `2.5rem 2fr 3fr auto`, with `1.5rem` gaps.
- Below `48rem`, stack each plugin row; retain its index beside the title.

Full-bleed bands must sit outside the constrained content wrapper. Do not use `width: 100vw` or negative-margin tricks that create horizontal overflow.

### Detail without clutter

Use disclosures for command explanations, evidence formats, and ownership mechanics.

- Disclosure summary: minimum `2.75rem` target height.
- Expanded content: `1rem` top padding.
- Nesting depth: maximum one.
- Installation, blockers, and compatibility limits must not be collapsed by default.
- Tables and code blocks may scroll within their own labelled containers. The page must not scroll horizontally at `320px`.

---

## 5. Component blueprints & states

### Buttons

Shared geometry:

- Minimum height: `2.75rem`.
- Padding: `0.75rem 1rem`.
- Border: `1px`.
- Radius: `--radius-control`.
- Type: UI/control.
- Icon: `1rem`, stroke width `1.75px`.
- Minimum icon-only target: `2.75rem × 2.75rem`.
- Use links for navigation and buttons for actions.

| Variant | Default | Hover | Active/pressed |
|---|---|---|---|
| Primary | Accent fill, on-accent text, strong border | Accent-hover fill | Accent-pressed fill; `translateY(1px)` |
| Secondary | Transparent fill, high text, strong border | Secondary surface | Recessed surface; `translateY(1px)` |
| Ghost | Transparent fill and border, high text, underlined label | Secondary surface | Recessed surface; no translation |

All variants:

- Focus-visible: `3px solid var(--focus-ring)` outline, `3px` offset.
- Colour and border transitions: `120ms var(--ease-ui)`.
- Press movement: `80ms var(--ease-ui)`.
- Disabled: recessed fill, muted text, subtle border, no hover or movement; use native disabled semantics where applicable.
- Loading: preserve width, show `Working…`, set `aria-busy="true"`, and prevent duplicate actions.
- Never remove focus outlines without the specified replacement.
- Only one filled primary action per section.

### Panels and cards

Use flat panels for installation, evidence, and technical examples.

- Background: secondary surface.
- Border: `1px solid var(--border-subtle)`.
- Radius: `--radius-panel`.
- Padding: `1.5rem`, reducing to `1rem` below `48rem`.
- Shadow: none.
- Backdrop filter: none.
- Heading-to-content gap: `0.75rem`.
- Noninteractive panels have no hover state.

An interactive panel uses a strong border. Hover changes its surface to recessed and its border to high text. Do not lift, tilt, or scale cards.

Use one main link per linked panel. Do not nest buttons inside a whole-panel link.

### Terminal and installation panel

- Use terminal-specific colour tokens in both themes.
- Padding: `1.5rem` desktop, `1rem` mobile.
- Header height: minimum `2.75rem`.
- Code: mono, `0.875rem`, line-height `1.6`.
- Command rows: `0.75rem` separation.
- Preserve command text as selectable HTML.
- Copy controls copy commands without `$` prompts or commentary.
- Copy success reads `Copied` for `2000ms` and uses a polite live region.
- Copy failure exposes `Select and copy the command`.
- Provide accessible horizontal scrolling for long commands.
- Do not add fake traffic-light window buttons or an endlessly blinking cursor.

### Inputs and dropdowns

- Input height: minimum `2.75rem`.
- Inline padding: `0.75rem`.
- Background: primary surface.
- Text: high contrast.
- Border: `1px solid var(--border-strong)`.
- Radius: control radius.
- Font size: `1rem`, including on mobile.
- Visible label: `0.875rem`, weight `600`, margin-bottom `0.5rem`.
- Placeholder: muted text; never a replacement for a label.

States:

| State | Requirement |
|---|---|
| Hover | Border becomes high text |
| Focus-visible | Shared `3px` focus ring |
| Error | Error-coloured border, `aria-invalid`, explicit message beneath |
| Disabled | Recessed surface, muted text, native disabled state |
| Read-only | Recessed surface, selectable value, visible read-only description |

Prefer native selects. Custom dropdowns are justified only when search or grouped results require them.

Custom menu geometry:

- Gap from trigger: `0.5rem`.
- Padding: `0.25rem`.
- Maximum height: `20rem`, with internal scrolling.
- Keep the menu inside the visual viewport with a `0.5rem` edge inset. Open below when it fits; otherwise use the side with more available space, preserving the `0.5rem` trigger gap. Set its maximum height to the smaller of `20rem` and that side's available height after the gap and inset. Clamp its horizontal position and width to the same viewport inset. Recalculate on scroll, resize, and visual-viewport changes, including the on-screen keyboard.
- If neither side can show one `2.75rem` option plus `0.5rem` total padding and the two `1px` borders, use a viewport-inset dialog with internal scrolling and focus return to the trigger instead of an anchored menu.
- Option height: minimum `2.75rem`.
- Background: primary surface.
- Border: strong.
- Radius: panel radius.
- Shadow: floating token.
- Selected option: checkmark plus text.
- Keyboard behavior: arrows, Home, End, Enter, Escape, and correct focus return.

Retain MkDocs search behavior and accessibility when restyling its interface.

### Badges and status indicators

- Font: mono, `0.6875rem`, weight `500`.
- Tracking: `0.03em`.
- Padding: `0.25rem 0.5rem`.
- Minimum height: `1.5rem`.
- Radius: `0.25rem`.
- Border: `1px solid currentColor`.
- Icon: `0.75rem`.
- Gap: `0.375rem`.

| Meaning | Colour | Required label example |
|---|---|---|
| Verified result | Success | `Verified locally` |
| Partial or pending result | Warning | `Partial evidence` |
| Failed result | Error | `Check failed` |
| Unknown or untested | Muted | `Not tested` |

Do not convert an unknown result into a warning or failure without evidence. A green status never implies merge, release, or deployment unless the label names that event.

### Diagrams and illustrations

- SVG is preferred.
- Line weight: `2px`.
- Node radius: `4px`.
- Node padding: `16px`.
- Minimum node separation: `24px`.
- Labels: body family, `14px`, line-height `1.4`.
- Use surface, text, border, and accent tokens.
- Give meaningful diagrams a text equivalent.
- Decorative plugin illustrations are `aria-hidden`.
- On small screens, reflow architecture diagrams vertically rather than shrinking labels below `14px`.

### Motion

Motion explains a transition or directs attention to a result.

| Interaction | Duration | Curve | Movement |
|---|---:|---|---|
| Control colour change | `120ms` | UI | None |
| Press | `80ms` | UI | `translateY(1px)` |
| Menu opening | `180ms` | Out | Opacity 0→1; Y `4px`→0 |
| Hero illustration entrance | `420ms` | Out | Opacity 0→1; Y `12px`→0 |
| Architecture path demonstration | `1200ms` total | Linear | One sequential path highlight |
| Copy feedback | `120ms` | UI | Label crossfade |

- Hero copy and installation commands are immediately visible.
- Only decorative hero elements may animate on entry.
- Automatic entry animations have a maximum stagger of `60ms` and a maximum complete sequence of `600ms`, including stagger delays.
- Architecture motion starts through an explicit `Trace a workflow` control and runs once for `1200ms` total. This user-triggered demonstration is outside the automatic entry-animation cap.
- No looping animation except a bounded loading indicator during actual work.
- Do not animate layout dimensions for decoration.
- Never use `transition: all`.
- Under `prefers-reduced-motion: reduce`, remove transforms, entrance animation, path animation, smooth scrolling, and animated loaders. Show final states and static loading text.

### Video and asset budgets

- Video playback starts only after explicit interaction.
- Use native controls, `playsinline`, and `preload="none"`.
- Poster: maximum `180KB`.
- Initial-page images combined: maximum `350KB`.
- Initial font transfer: maximum `250KB`.
- Additional custom JavaScript: maximum `20KB` compressed.
- First-workflow video: maximum `12MB`; target duration at most `90 seconds`.
- If real execution takes longer, use labelled edits and preserve the measured elapsed time.
- Supply a text transcript and captions for speech or instructional audio.
- Reserve image and video dimensions before loading.
- Lazy-load media below the first viewport.
- If a recording is unavailable, show the real static procedure. Never substitute a fabricated success animation.

---

## 6. Agent implementation rules

These six rules are mandatory.

1. **Preserve the product contract.** Keep MkDocs, existing document URLs, working commands, and the separation between local tools and T3 orchestration. Derive plugin names and capabilities from repository sources. Never invent execution results, speed claims, provider support, or completion evidence.

2. **Use the specified system.** Implement the font scale, spacing, HSL tokens, radii, component states, and motion timings exactly. Scope Material overrides deliberately. No unexplained colours, arbitrary spacing, gradients, glass effects, or replacement component-library styling.

3. **Make every layout survive constrained space.** Verify at `320px`, `390px`, `768px`, `1280px`, and `1536px`, plus `200%` zoom. No page-level horizontal overflow. Keep prose within `65ch`, controls at least `44px` high, and inputs at least `16px` at the default root size. Reusable panels must work inside narrow containers; use container queries where behavior depends on panel width.

4. **Make every interaction accessible.** Provide semantic landmarks, one H1, ordered headings, a skip link, visible focus, keyboard operation, labelled controls, and meaningful status text. Verify contrast in both themes. Support reduced motion. Core documentation, navigation, and installation instructions remain usable without custom JavaScript.

5. **Specify incomplete states before the happy path ships.** Search requires empty and no-results states; copy requires success and failure states; media requires a poster and load-failure fallback. Async work requires loading, error, and retry behavior. Static documentation must not display artificial skeletons. Genuine skeletons reserve final dimensions, use the recessed surface, and never shimmer.

6. **Verify the shipped artifact.** From the repository root, create the documentation environment with `python3.12 -m venv .venv-docs` (Python 3.12 matches documentation CI), then install dependencies with `.venv-docs/bin/python -m pip install -r requirements-docs.txt`. Run `.venv-docs/bin/python -m unittest discover -s tests -v`, `.venv-docs/bin/python scripts/check_docs.py`, and `.venv-docs/bin/python -m mkdocs build --strict`. See [the contributor guide](docs/contributing.md#work-on-the-site) for the local preview workflow. Inspect the built site on desktop and mobile in both themes. Check keyboard navigation, reduced motion, command copying, link destinations, media behavior, console errors, and asset budgets. Record unavailable checks explicitly. A passing build is not proof of rendering quality, deployment, or live acceptance.
