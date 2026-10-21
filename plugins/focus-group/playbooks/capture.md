# Capture and validate the shared pack

Used by `plan`, step 3. Capture is read-only and happens before approval. Every cell
gets the same pack at the same common capture profile; v1 never varies it by
persona. The helper is `python3 PKG/scripts/evidence.py`; record shapes are in
`PKG/references/evidence-contract.md`.

## 1. Choose a safe context

Use a verified fresh anonymous host context. The alternative is an isolated,
host-preauthenticated test context that the owner approved explicitly. Never use
the operator's personal, default or saved browsing profile. For a test context, ask
through the native question picker with the option
`Approve isolated test context <reference> for focus-group capture` and save that
single answer to a file outside the job directory.

If neither can be established, hold automatic capture. Offer the owner a supplied
pack with equivalent declared provenance instead. Never invent freshness or fall
back to a personal profile.

## 2. Capture to new files

Use the plan's `capture_profile` (default: a phone viewport). Save the initial
viewport and one screenshot per listed extra view as PNG (v1 scans PNG only), and
page text as UTF-8.
Write every attempt to new file names. A failed attempt keeps its files, and a
recapture is attempt `n + 1` naming the previous manifest.

Fill `PKG/templates/capture-manifest.example.json`. Record the context class,
the host's reference for the capture context (required, fresh contexts included;
never invent one), freshness check, known test cookies/storage/onboarding state and
whether the material represents a new or returning user. Also record the
requested and final URL and the HTTP status. When the mechanism does not expose
the status, record `unavailable-from-mechanism`; rendering is not proof of 200.
Add the capture time, observed readiness, file hashes, limits, and device/access
needs not exercised. An accessibility persona does not establish
assistive-technology testing.

## 3. Inspect, then validate

Look at every image and read every text file yourself before validating. Record
`viewed`, `blank`, `error_page`, `secrets_visible` and `personal_data_visible` for
each file in `inspection`. Then:

```sh
python3 PKG/scripts/evidence.py pack --state-root ROOT --study ID --input manifest.json
```

- `cleared`: copy `data.stimulus` into the draft and set
  `coordinator_inspected: true`. Approval checks this exact verdict, files,
  provenance and profile.
- `failed`: missing, blank, error, uninspected or drifted material, failed
  readiness, a personal profile, or an unrecorded status. Fix the cause and
  recapture.
- `held`: a supplied pack with unresolved provenance. Ask the owner for the
  missing facts; never fill them in.
- `quarantined`: suspected secrets or personal account data. The material is not
  disclosed to any participant, analyst, reviewer or export. Make a sanitised
  copy with new files and a manifest whose `derived_from` names the quarantined
  manifest. The derivative is a new pack, a new revision and a new approval.

Diagnostics name the file, class, offset and length of each suspect match, never
its value. A scan finds known shapes only; the coordinator's own inspection still
decides what is visible in images.

When the pack is non-fresh (an approved test context, or known state), report that
state beside every first-impression finding.
