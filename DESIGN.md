# DESIGN.md

The visual system for the t3-plugins documentation site. It is implemented in
`docs/stylesheets/extra.css`, `overrides/`, and `docs/assets/`, and generated from
repository data by `scripts/field_guide.py`. This document describes what is built
so the next change stays consistent with it. Where the site and this file disagree,
fix one of them in the same pull request.

## 1. Direction: a field guide

**Change the model. Keep the workflow.**

The site is a naturalist's field guide to seven workflows. The metaphor is chosen
because it is literally true of the project: the plugins have creature names, the
catalog is a numbered set of specimens, and the compatibility ledger records
sightings rather than promises. The structure carries the idea. The prose stays
plain.

What that means in practice:

- **Plates.** Each plugin is Plate I to VII, in the order the homepage key lists them. The numeral is decoration only when it is not also the order, so the order is enforced by `tests/test_field_guide.py`.
- **Specimen marks.** One two-ink silhouette per plugin under `docs/assets/specimens/`, drawn once in `<defs>` and printed twice: a fern copy offset by 2.5 units behind the ink copy, like a misregistered print. Marks use CSS custom properties with hex fallbacks, so they recolour in dark mode when inlined and still render inside a README `<img>`.
- **One binomial per plugin.** A short italic Latin-style name beside the plugin name, once on the homepage key and once on the plugin page. Nowhere else. It is the single quiet joke; do not add more.
- **Sightings.** The live conformance ledger is rendered as a table of filled and empty marks with the numbers beside them. A unit test is not a sighting. "not run" is a result.
- **Dry copy.** No mascot voice, no exclamation marks, no field-guide vocabulary in body text beyond the four structural words: plate, specimen, habitat, diet, field marks, sightings.

Things the site deliberately does not have: gradients, glass panels, drop shadows,
rounded promotional cards, uppercase eyebrow labels, provider logo walls, stock
imagery, and animated entrances on scroll.

## 2. Typography

| Role | Family | File | Weights |
|---|---|---|---|
| Display and headings h1, h2 | Fraunces (variable, optical size axis) | `docs/assets/fonts/fraunces-variable.woff2`, `fraunces-italic-variable.woff2` | 500 to 700, italic for binomials and plate numbers |
| Body, h3, h4, UI | IBM Plex Sans (variable) | `docs/assets/fonts/ibm-plex-sans-variable.woff2` | 400, 500, 600 |
| Code, commands, data | IBM Plex Mono | `docs/assets/fonts/ibm-plex-mono-400.woff2`, `ibm-plex-mono-500.woff2` | 400, 500 |

All faces are bundled (SIL Open Font License 1.1, texts in
`docs/assets/fonts/LICENSE.txt`) with `font-display: swap`. The site makes no
third-party requests; `theme.font` stays `false` in `mkdocs.yml`.

Scale, in Material's rem where `1rem = 20px`:

| Role | Size | Weight | Tracking | Line height |
|---|---:|---:|---:|---:|
| Hero headline | `clamp(2.2rem, 4.6vw, 3.3rem)`; `clamp(1.9rem, 10.5vw, 2.3rem)` below 45em | 600 | `-0.025em` | 1.02 |
| h1 | `2.1rem` | 600 | `-0.02em` | 1.1 |
| h2 | `1.4rem`, hairline rule above | 500 | `-0.01em` | 1.2 |
| h3 | `0.95rem` Plex Sans | 600 | `-0.005em` | default |
| Lead | `0.92rem` | 400 | 0 | 1.55 |
| Body | `0.8rem` | 400 | 0 | 1.65 |
| Code | `0.78em` inline, `0.74em` in blocks | 400 | 0 | 1.7 |
| Plate number, binomial | Fraunces italic `0.72rem` to `1rem` | 500 | 0 | default |
| Data labels (operations, sightings) | Plex Mono `0.62rem` to `0.68rem` | 400 to 500 | 0 | 1.6 |

Rules: sentence case everywhere; no uppercase labels; body measure stays under
80 characters; links are underlined with a 1px line at `0.18em` offset in a
45 percent fern, full colour on hover.

## 3. Colour

Two inks on toned paper. Light is "herbarium", dark is "night survey". Every colour
on the site comes from these tokens, and Material's own variables are mapped to
them in `extra.css`.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--paper` | `#eef0e8` | `#15201b` | Page |
| `--paper-deep` | `#e2e6da` | `#1d2b25` | Code, install line, footer, search field |
| `--ink` | `#1f2a24` | `#e6eae0` | Text, strong rules, primary button |
| `--ink-soft` | `#55615a` | `#a6b1a8` | Secondary text, captions |
| `--rule` | `#c6cdbf` | `#2f3e37` | Hairlines, table rows, plate inner frame |
| `--fern` | `#2f6b4f` | `#7bc49a` | Links, second ink in specimen marks, clean sightings |
| `--fern-deep` | `#1f4d38` | `#9ad6b2` | Hover |
| `--ochre` | `#b8862b` | `#d9ae5a` | Specimen accents (goldfish, beak, twig) |
| `--ochre-text` | `#80601a` | `#d9ae5a` | Plate numbers, mixed sightings; passes 4.5:1 on paper |
| `--madder` | `#a8402f` | `#e07a66` | Failed sightings only |

The specimen marks read `--sp-ink`, `--sp-paper`, `--sp-fern`, `--sp-ochre`, which
the stylesheet aliases to the tokens above. Status chips use `currentColor`
borders: fern for verified, ochre-text for partial, ink-soft for unavailable,
madder for failed. Colour never carries a status alone; the text does.

Contrast gates: 4.5:1 for body text and 3:1 for large text and control
boundaries, in both schemes, including hover and focus. `--ochre` itself is
never used for text smaller than 1rem; use `--ochre-text`.

## 4. Layout

- Content width is Material's `61rem` grid; the homepage sections use `.fg-wrap` with the same maximum.
- Hero: two columns at `minmax(0, 1.15fr) minmax(0, .85fr)` above 60em, stacked below. Text column first on mobile, then the plate.
- Plate frame: 1px ink border with a second hairline 5px inside, plate number top left, mark at 60 percent width, ruled caption with name, binomial, and summary.
- Homepage key: an ordered list of rows, `2.2rem 3.4rem minmax(0, 11rem) minmax(0, 1fr) minmax(0, 11rem)` at large widths, collapsing to three columns below 76em and stacking the summary and operations under the name. Rows are separated by hairlines; the list has an ink rule above its heading.
- Plugin page header: a `6.4rem` mark beside plate number, binomial, and a definition list of habitat, diet, and field marks, inside a hairline frame.
- Sightings table: full width, hairline rows, ink rule under the header, row headings top-aligned with their cells, model names wrapping only at hyphens, caption below in ink-soft; horizontal scroll inside its own container below 45em with a `40rem` minimum.
- Tables elsewhere: no zebra, no box shadow, ink rule under headers, hairline rows.
- Admonitions: a 2px fern left rule, no background.
- Spacing is in Material rem; hero `3rem` top and `2.4rem` bottom on desktop, `1.8rem` and `1.6rem` on mobile; key rows `1rem` vertical.

Verify at 390px, 768px, 1280px, and 200 percent zoom. No page-level horizontal
overflow at 390px; the install line scrolls inside its own box.

## 5. Components

- **Buttons.** 1px ink border, 4px radius, Plex Sans 500 at `0.74rem`. Primary is ink fill with paper text, hovering to fern-deep with paper text (never a fixed white, which fails on dark mode's pale fern). Focus is a 2px `--ochre-text` outline. Secondary is transparent, hovering to paper-deep. One primary per section.
- **Install line.** Plex Mono in a paper-deep box with a hairline border and a `$` prompt drawn by CSS so copying the text copies the command only.
- **Specimen marks.** 96 by 96 viewBox, `role="img"` with an `aria-label`, no scripts, no external references. Tests enforce this.
- **Sightings marks.** Filled and empty circles followed by `passed/repeats`, with an `aria-label` carrying the same numbers. States: clean (fern), mixed (ochre-text), failed (madder), not run (ink-soft italic).
- **Recording.** `docs/assets/demo.svg`, generated by `scripts/render_demo.py`, is a scripted recording whose styles and animation names are scoped to its `.demo-rec` root (it is inlined into the page), whose canvas widens to fit the longest line, with its total length in the corner and a caption that says it is not a live model call. Commands are typed with a stepped clip animation; output lines appear at their timestamps; `prefers-reduced-motion` shows the final frame. The shell frames come from real CLI output; the T3 thread frames illustrate what `doctor` reports. Do not present it as footage, and do not replace it with a fabricated success animation. Real footage, when recorded, follows the measurement rules below.
- **Diagrams.** Inline SVG through the hook's `<!-- inline-svg: -->` marker so page fonts and tokens apply. 1.3px ink strokes, no fills, `Fig.` label in ochre-text italic, text in Plex Sans at 15 to 17px, a `<title>` and `<desc>`. The hook wraps each one in a `.diagram-frame`; below 45em the diagram keeps a `40rem` minimum and scrolls sideways, like the tables, rather than shrinking its labels.

## 6. Motion

One orchestrated moment per page at most. On the homepage that is the recording.
Hover changes are colour and underline thickness only. No entrance animations, no
parallax, no cursor effects, no looping motion. `prefers-reduced-motion: reduce`
disables all animation and transitions globally.

## 7. Data flow

The site is generated from the repository, never hand-copied:

- `plugins/*/plugin.json` supplies name, description, version, operations.
- `docs/field-guide.json` supplies plate, binomial, summary, habitat, diet, field marks. Every plugin needs an entry and every entry needs a plugin; plates run I to N without gaps; each plugin needs a mark. The build fails otherwise.
- `conformance/compatibility.json` supplies the sightings table and the version caption.
- `scripts/field_guide.py` assembles these in `on_config`, renders the specimen header after each plugin page's h1, expands `<!-- sightings-matrix -->`, and inlines SVGs from `docs/assets/` only.

Adding a plugin: add the manifest, the guide entry, the mark, and the page. Nothing
else on the site needs editing.

## 8. Measurement rules for real footage

When a real recording of installation and the first T3 readiness report exists,
it replaces the scripted one under these rules: show the package version, date,
and environment; time installation and the T3 readiness check separately; label
warm caches, cuts, and playback speed; publish elapsed-time claims only after
measuring them; keep terminal output uncropped; supply a transcript. A reported
missing capability is a legitimate result and stays in the cut.

## 9. Verification before merging a site change

From the repository root:

```sh
python3 -m venv .venv-docs
.venv-docs/bin/pip install -r requirements-docs.txt
python3 -m unittest discover -s tests -p 'test_field_guide.py'
python3 -m unittest discover -s tests -p 'test_render_demo.py'
python3 scripts/check_docs.py
.venv-docs/bin/python -m mkdocs build --strict
```

Then look at the built site at 390px and 1280px in both schemes, with keyboard
focus visible and reduced motion on. A passing build is not proof of rendering
quality; a screenshot of the real artifact is. Headless Chrome with
`--virtual-time-budget` advances the recording for screenshots.
