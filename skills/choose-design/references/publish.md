# Publish the comparison

Publish every checked and scored option set to the owner's private S3 base and
present one presigned URL beside the T3 frames. Invoking `choose-design`
authorizes uploading only that run's option HTML and generated index to the
configured private base, including from an authorized workflow. It does not
authorize public access, another destination, or sending the link beyond the
user. Explicit user or standing sharing limits override this grant.

## Destination and prerequisites

The destination is host configuration, never repository source. Read:

- `CHOOSE_DESIGN_S3`: `s3://bucket` or `s3://bucket/base-prefix`.
- `AWS_PROFILE`: the standard AWS CLI profile. Keep the endpoint, key and bucket
  out of this repository.

If `CHOOSE_DESIGN_S3` is unset, report `publishing not configured` and continue
with inline or file presentation; mark the S3 result incomplete. Do the same for
a missing CLI, failed credentials, upload or presign, naming the exact failure.
Never block the user's choice.

The signing profile must not expire before the link deadline. Static keys, or a
`credential_process` whose JSON has no `Expiration`, are suitable. If an
expiration is exposed and falls inside the window, use that earlier time as the
deadline; if it is unknown, do not promise seven days.

The link is a bearer token. Share it only with the user or recipients the user
authorized.

## Claim a run prefix

Publish after checks and scoring, before presenting. Only eligible options go
live: self-contained HTML, no remote assets, and controls that work under an
opaque-origin sandbox. An option needing cookies, storage, form submission,
popups or remote requests is not eligible; keep it in the inline set and apply
the [static fallback](reports.md) to that control, labelled unverified.

Each run owns a unique prefix; never list a date folder and assume it is free.

```sh
base=${CHOOSE_DESIGN_S3%/}
rest=${base#s3://}
bucket=${rest%%/*}
basekey=${rest#*/}
[ "$basekey" = "$rest" ] && basekey=
slug=$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')
[ -n "$slug" ] || slug=design
date=$(date +%Y-%m-%d)
for attempt in 1 2 3; do
  token=$(python3 -c 'import uuid; print(uuid.uuid4().hex[:16])')
  prefix="${basekey:+$basekey/}${slug}/design-options-${date}-${token}/"
  count=$(aws s3api list-objects-v2 --bucket "$bucket" --prefix "$prefix" --max-keys 1 --query KeyCount --output text)
  [ "$count" = 0 ] && break
done
[ "$count" = 0 ] || { echo "could not claim a prefix"; exit 1; }
```

Use a project slug from the repository directory. A task slug is a fallback.
Record the exact bucket, prefix and every key; cleanup uses only those.

## Upload and sign

Upload each option under its label. Upload nothing else: no briefs, repository
files, screenshots with real data, secrets or personal data.

```sh
aws s3 cp A1.html "s3://$bucket/${prefix}A1.html" \
  --content-type 'text/html; charset=utf-8' --cache-control 'no-store'
aws s3 presign "s3://$bucket/${prefix}A1.html" --expires-in 604800
```

Repeat for each option, collecting the presigned URLs. Sign options first,
build the index with those absolute URLs, then upload and sign the index last.

```sh
aws s3 cp index.html "s3://$bucket/${prefix}index.html" \
  --content-type 'text/html; charset=utf-8' --cache-control 'no-store'
aws s3 presign "s3://$bucket/${prefix}index.html" --expires-in 604800
```
Compute the earliest effective expiry from each URL's `X-Amz-Date` plus
`X-Amz-Expires` (or the credential lifetime, if shorter). State one deadline in
Australia/Sydney time, for example `All links expire 1 December 2026 at 2:20 pm
AEDT`.

## Index contract

The uploaded `index.html` contains no JavaScript. Keep the CSS scoped to
`.option-frame`; an unscoped `iframe` selector also styles Cloudflare's hidden
injected frame.

- Header: request or project title, one-line lead, deadline.
- One section per designer (`A · Opus`), each with a `.scroller` region and a
  `.grid` of two 728px columns and a 24px gap.
- Each card header outside the frame: label, model, name, two-to-four-sentence
  blurb, both reviewers' scores and one-line notes, and a direct-open link.
- Each frame: `class="option-frame"`, `width="728"`, the height measured by
  `html_preview` (`height="1600"` only as a labelled fallback),
  `sandbox="allow-scripts"` with no `allow-same-origin`,
  `referrerpolicy="no-referrer"`, `loading="lazy"`, and a descriptive `title`.
- Direct links: the presigned URL as-is, `target="_blank"` and
  `rel="noopener noreferrer"`.
- Footer: `Mockups only, nothing built yet.` System fonts, no remote assets,
  visible focus.

```html
<article class="card">
  <div class="card-head">
    <p class="id">A1 · Opus</p>
    <h2>Noticeboard</h2>
    <p class="blurb">Warm noticeboard look …</p>
    <p class="scores">Neon 8/10 · Sol 7/10</p>
    <p class="notes">Neon: clear hierarchy. Sol: chips crowd the first row.</p>
    <p class="open"><a href="PRESIGNED_URL" target="_blank"
      rel="noopener noreferrer">Open A1 on its own</a></p>
  </div>
  <iframe class="option-frame" src="PRESIGNED_URL" width="728" height="560"
    sandbox="allow-scripts" referrerpolicy="no-referrer" loading="lazy"
    title="A1 Noticeboard mockup"></iframe>
</article>
```

Use the measured height for the frame. A 1600px fallback may scroll internally;
note the fallback in the page footer when it applies. Do not add an auto-height
script: the index must stay script-free and the sandbox gives each option an
opaque origin.

## Check and report

Before reporting the run as published:

- Fetch the index and one option through the presigned URLs; both must return
  200 and `text/html`.
- Confirm the uploaded index source has no `<script>`. A served response may
  contain Cloudflare's injected challenge script(s); any script not matching
  `__CF$cv$params` or `cdn-cgi/challenge-platform` is a failure.
- In a browser, check a wide viewport (two frames per row), a narrow viewport
  (the scroller moves to the second frame), a control inside a sandboxed frame,
  the fixed-height fallback's internal scroll, and the direct-open link.
- Record the index URL, exact prefix and keys, deadline, and any option that used
  the static fallback.

## Clean up

After the user chooses, delete the recorded keys. Do not use
`aws s3 rm --recursive`; this Garage endpoint rejects it with
`signed header content-length is not present`.

```sh
aws s3api delete-object --bucket "$bucket" --key "${prefix}index.html"
aws s3api delete-object --bucket "$bucket" --key "${prefix}A1.html"
aws s3api list-objects-v2 --bucket "$bucket" --prefix "$prefix" --max-keys 1 --query KeyCount --output text
```

Require `0` from the listing, then confirm the original signed index and one
option URL now fail (403 or 404). A signed GET for a deleted object returned
404 in testing. Keep the objects if the user asks.

If the user makes no choice, leave the objects. The links expire; the private
objects remain until the user asks for cleanup. Report that fact rather than
claiming the run was deleted.

On a partial failure, delete only this run's uploaded keys, report the exact
error, and keep the inline comparison and the choice available.
