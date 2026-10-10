# Saved evaluation evidence

A suite contains at least three cases, one each of `normal`, `edge`, and `adversarial`:

```json
{"cases":[{"id":"normal-1","kind":"normal","input":"fixture input","checks":[{"equals":"expected output"}]}]}
```

The one-case example shows the shape only. IDs are unique and each checks array is
nonempty. Predicates are `equals`, `contains`, `not_contains` (strings), or `json_equals`.
Each run records the exact prompt, model, settings, all inputs, and actual outputs:

```json
{"prompt":"exact prompt","model":"resolved-model-id","settings":{},"inputs":{"normal-1":"fixture input"},"outputs":{"normal-1":"actual output"}}
```

Run `python3 PKG/scripts/evaluate.py suite.json baseline.json candidate.json`.
Exit 0 means at least one prompt passed all supplied cases; 1 means neither did;
2 means evidence was invalid or incomparable. The receipt includes file hashes,
per-case results, and prompt byte counts. Retain runner transcripts or response IDs.
Hashes identify submitted files; they do not authenticate model execution. These
checks cannot establish general writing quality or semantic correctness.
