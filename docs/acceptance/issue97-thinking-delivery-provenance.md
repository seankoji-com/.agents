# Issue #97: controlled Markdown delivery provenance

This acceptance fixture exercises the released thinking workflow. Publication grants no product implementation authority.

| Evidence | Identity |
| --- | --- |
| Installed release | v0.11.0, source `c11412c89c1a36820569d7330b19489b03069164` |
| Owner-accepted discovery SHA-256 | `9e56240fd6c2bc629068f1e4093024a031780cc7672bc1eb9f3876fc94f4db5f` |
| Independently accepted source snapshot | `2b1df9825c4bc967d71892d30b73c14e4bfec38d45bf235480943c52fe359fc2` |
| Complete handoff SHA-256 | `8561798e831a65feb0658255c2ef6b5b7e9b09493ddb7f648fc077e79f19b868` |
| Source author | OpenAI, Sol |
| Planning reviewer | Qwen 3.8 Flash, high; the Qwen reviewer serves as the selected cross-lineage backup to the Grok review chain |

## What each digest covers

**Complete handoff** `8561798e...` covers every byte of `docs/acceptance/issue97-thinking-delivery.md` at this pull request's head: the whole file, including its header and wrapper headings, 6,612 bytes. Recompute with `sha256sum docs/acceptance/issue97-thinking-delivery.md`.

**Owner-accepted discovery** `9e56240f...` covers only the discovery block inside that file. It runs from the `# Controlled acceptance fixture for issue #97` heading through the last line of `## 7 Open questions`, 2,921 bytes, and excludes the wrapper `## Discovery` heading above it plus the blank lines before `## Evaluation criteria`. Recompute:

```sh
python3 -c "import hashlib,pathlib;t=pathlib.Path('docs/acceptance/issue97-thinking-delivery.md').read_text();b=t[t.index('# Controlled acceptance fixture for issue #97\n'):t.index('## Evaluation criteria')].rstrip('\n')+'\n';print(len(b),hashlib.sha256(b.encode()).hexdigest())"
```

That prints `2921 9e56240f...`. The evaluation-criteria block after it keeps its own boundary in the same way, from `# Controlled thinking delivery specification` through the grading notes; no digest in this table records it separately.

**Independently accepted source snapshot** `2b1df982...` covers the source-plan snapshot that the planning job froze for review. That snapshot is not retained in this repository, so the value is recorded as received and cannot be recomputed from these two files. No other artifact in this pull request corroborates it.

## Historical status inside the retained bytes

The retained discovery still opens with its preparation status. Line 17 of `issue97-thinking-delivery.md` reads:

> Author: OpenAI. Prepared discovery; owner review pending. No product implementation is requested.

That line is historical, not current. The owner's content-bound acceptance on 24 October 2026 (AEDT, UTC+11) supersedes it, and the retained file is deliberately left byte-identical: the digests above are the evidence this fixture exists to carry, so the supersession marker lives here instead of inside the accepted bytes.

## Label conventions

`[REQ-...]` and `[verify:...]` in the retained discovery and evaluation criteria are tokens of this repository's requirement contract, not prose emphasis. `core/contract.py` parses `[REQ-ID]` and `[verify:(inspection|command|runtime|manual)]` from Definition-of-done items, `plugins/elephant-goldfish/templates/spec.skeleton.md` states the convention, and `docs/design/imps-t3/spec.md` uses it in practice. They appear here because the accepted specification is quoted unchanged. The `[REQ-FIXTURE-*]` identifiers are that specification's own requirement IDs; the planning review's `requirements` input maps each one to its acceptance statement.

## Binding and outstanding gates

The adjacent `issue97-thinking-delivery.md` preserves the complete accepted handoff bytes, digest `8561798e...`. The owner acceptance binds that content, and the discovery it accepted is the `9e56240f...` block defined above. Both digests are recomputable from the retained file, so a reviewer can check the binding without trusting this prose.

The fixture targets `master` and is restricted to these two Markdown paths. Its head requires independent review and the repository's local and hosted checks. This provenance records planning acceptance; it does not claim those later gates have passed.

## Retained publication and continuation

[PR #131](https://github.com/seankoji-com/t3-plugins/pull/131) was amended and merged at `f2a610ad870a5e18517eb5054418fa39d575192a` before the coordinating workflow recorded its live completion. The coordinator's review and local checks covered the earlier head `2e69e10c52a940d3c8676e3d23a4833cab282e83`; they do not certify the later head.

This draft continuation preserves the same accepted handoff and discovery. It updates this provenance only, retains the prior PR as evidence, and requires its own current-head review and checks. It must be closed after verification, without merging. Publication grants no implementation authority.

Related evidence: [original work](https://github.com/seankoji-com/t3-plugins/issues/97), [released package](https://github.com/seankoji-com/t3-plugins/releases/tag/v0.11.0), [verified Issue fixture](https://github.com/seankoji-com/t3-plugins/issues/128).
