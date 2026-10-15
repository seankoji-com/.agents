#!/usr/bin/env python3
"""render_handoff.py — assemble handoff.md, the input to step 3.

`handoff.md` is the deliverable of elephant-goldfish `thinking <topic>`: a single self-contained
document you paste as the first message of a fresh session (or hand to imps in T3). It is
pure concatenation of documents that already exist on disk, so the model must never
generate it — having a model re-emit discovery.md and spec.md into a third file costs
output tokens at output-token prices to produce bytes that are already sitting there,
and introduces a chance of paraphrasing the brief it is supposed to reproduce verbatim.

Templates live in ../templates/handoff.<output_type>.md and are chosen from meta.json's
output_type, so the research and implementation paths differ in framing without the
caller deciding anything at render time.

Usage:
  render_handoff.py <slug> [--root DIR] [--template-dir DIR] [--stdout] [--draft] [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from thinking_state import DRAFT_MARKER, StateError, cmd_gate, handoff_problem, read_meta

DEFAULT_ROOT = "thinking"
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


class RenderError(Exception):
    pass


def default_template_dir() -> Path:
    """Resolve bundled templates relative to this file — never an absolute machine path.

    T3_PLUGIN_ROOT is honoured when set (that is how the command invokes it), but the
    __file__-relative fallback means the script also works when run directly from a
    checkout or a test harness.
    """

    root = os.environ.get("T3_PLUGIN_ROOT")
    if root:
        candidate = Path(root) / "templates"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent.parent / "templates"


def read_required(path: Path, what: str) -> str:
    if not path.exists():
        raise RenderError(f"missing {what}: {path} — run the earlier phase first")
    with path.open(encoding="utf-8", newline='') as stream:
        text = stream.read()
    if not text.strip():
        raise RenderError(f"{what} at {path} is empty")
    return text


def render(template: str, values: dict) -> str:
    """Substitute {{PLACEHOLDER}} tokens found in the TEMPLATE. User content stays inert.

    The unknown-placeholder check runs against the template *before* substitution, never
    against the result. Scanning the output conflates two different things: a typo in a
    template we ship, and a brace pair inside the user's own documents. Only the first is a
    bug. The second is ordinary content — Mustache and Handlebars snippets, `{{API_KEY}}`
    style placeholders in API notes, or a discovery.md that discusses this plugin's own
    templates — and aborting on it would break the render of a document whose entire job is
    to reproduce discovery.md and spec.md verbatim.

    Substituted values are never rescanned: re.sub does not re-examine what a replacement
    function returns, so a `{{SPEC}}` inside discovery.md passes through as literal text
    rather than being treated as a placeholder or as an error.
    """
    unknown = sorted({key for key in PLACEHOLDER_RE.findall(template) if key not in values})
    if unknown:
        raise RenderError(
            "template references unknown placeholder(s): "
            + ", ".join("{{%s}}" % key for key in unknown)
        )
    return PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], template)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="render_handoff.py", description=__doc__.split("\n")[0])
    parser.add_argument("slug")
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--template-dir", default=None)
    parser.add_argument("--stdout", action="store_true", help="print instead of writing handoff.md")
    parser.add_argument("--check", action="store_true", help="verify saved input/output hashes without writing")
    parser.add_argument("--draft", action="store_true", help="render/check a non-executable handoff.draft.md")
    parser.add_argument("--capabilities", help="fresh orchestrator_capabilities JSON used to record this render author")
    args = parser.parse_args(argv)

    try:
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', args.slug):
            raise RenderError('topic slug must be lowercase kebab-case, 1-63 characters')
        tdir = Path(args.root) / args.slug
        if tdir.is_symlink() or not tdir.resolve().is_relative_to(Path(args.root).resolve()):
            raise RenderError('topic directory escapes the requested root')
        stem = "handoff.draft" if args.draft else "handoff"
        for name in ('meta.json', 'discovery.md', 'spec.md', f'{stem}.md', f'{stem}.manifest.json'):
            if (tdir / name).is_symlink():
                raise RenderError(f'topic file may not be a symlink: {name}')
        meta_file = tdir / "meta.json"
        if not meta_file.exists():
            raise RenderError(f"no topic {args.slug!r} under {args.root} — nothing to render")
        meta = read_meta(tdir)

        output_type = meta.get("output_type")
        if output_type not in ("research", "implementation"):
            raise RenderError(f"meta.json has invalid output_type {output_type!r}")

        if args.check:
            problem = handoff_problem(tdir, meta, draft=args.draft)
            if problem:
                raise RenderError(problem)
            print("handoff provenance verified; operator review/readiness and execution authority not verified")
            return 0

        if not args.stdout and not args.capabilities:
            raise RenderError("writing a handoff requires --capabilities with a fresh orchestrator_capabilities response")

        tpl_dir = Path(args.template_dir) if args.template_dir else default_template_dir()
        tpl_file = tpl_dir / f"handoff.{output_type}.md"
        if not tpl_file.exists():
            raise RenderError(f"missing template {tpl_file}")

        values = {
            "TOPIC_SLUG": args.slug,
            "TITLE": meta.get("title", args.slug),
            "OUTPUT_TYPE": output_type,
            "GENERATED_AT": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "DISCOVERY": read_required(tdir / "discovery.md", "discovery.md"),
            "SPEC": read_required(tdir / "spec.md", "spec.md"),
        }
        if args.draft:
            # A draft has no execution prompt, even for an implementation output type.
            out = (f"{DRAFT_MARKER}\n\n# Draft brief: {values['TITLE']}\n\n"
                   "DRAFT. Non-executable. Discovery review and final readiness are pending.\n"
                   "This document does not authorise implementation or research execution.\n\n"
                   f"## Problem definition\n\n{values['DISCOVERY']}\n\n"
                   f"## Proposed evaluation criteria\n\n{values['SPEC']}\n")
        else:
            gate = cmd_gate(argparse.Namespace(root=args.root, slug=args.slug,
                                              require="discovery,spec", draft=False))
            for key, filename in (("DISCOVERY", "discovery.md"), ("SPEC", "spec.md")):
                if hashlib.sha256(values[key].encode()).hexdigest() != gate["input_hashes"][filename]:
                    raise RenderError("inputs changed during readiness check; retry from reviewed inputs")
            out = render(tpl_file.read_text(encoding="utf-8"), values)
            out = (f"Review status: {gate['review']['status']}. Scope: finalise-brief.\n"
                   "This handoff does not authorise execution. A separate user instruction is required.\n\n"
                   + out)
        manifest = {
            "schema": 2,
            "status": "draft" if args.draft else "final",
            "topic": args.slug,
            "output_type": output_type,
            "discovery_sha256": hashlib.sha256(values["DISCOVERY"].encode()).hexdigest(),
            "spec_sha256": hashlib.sha256(values["SPEC"].encode()).hexdigest(),
            "handoff_sha256": hashlib.sha256(out.encode()).hexdigest(),
            "requirement_ids": list(dict.fromkeys(re.findall(r"\[(REQ-[A-Z0-9_-]+)\]", values["SPEC"]))),
        }
        if not args.draft:
            manifest["review_sha256"] = gate["review_sha256"]
        if not args.stdout:
            try:
                package_root = next((parent for parent in Path(__file__).resolve().parents
                                     if (parent / "shared" / "document_authors.py").is_file()), None)
                if package_root is None:
                    raise RenderError("shared document-author helpers are unavailable")
                sys.path.insert(0, str(package_root))
                from shared.document_authors import append_author
                from core.jobs.store import canonical
                cap_path = Path(args.capabilities)
                if cap_path.is_symlink() or not cap_path.is_file():
                    raise RenderError("capabilities file must be a regular file")
                capabilities = json.loads(cap_path.read_text(encoding="utf-8"))
                records_path = tdir / "document-authors.json"
                if records_path.is_symlink():
                    raise RenderError("document author records may not be a symlink")
                records = json.loads(records_path.read_text(encoding="utf-8")) if records_path.exists() else {}
                if not isinstance(records, dict):
                    raise RenderError("document author records must be an object")
                source_hashes = [manifest["discovery_sha256"], manifest["spec_sha256"]]
                records = append_author(records, out.encode("utf-8"), capabilities, source_hashes,
                                        tdir / "handoff.md")
                manifest["document_authors"] = records[manifest["handoff_sha256"]]
                temporary_records = records_path.with_name(records_path.name + ".tmp")
                temporary_records.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                os.replace(temporary_records, records_path)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise RenderError("cannot record handoff author lineage: " + str(exc)) from exc
        if args.stdout:
            sys.stdout.write(out)
        else:
            target = tdir / f"{stem}.md"
            # Each file is atomic. Consumers compare the output hash, so a crash between
            # the two replaces is detected instead of accepting a stale manifest.
            for dest, content in ((target, out), (tdir / f"{stem}.manifest.json", json.dumps(manifest, indent=2) + "\n")):
                fd, temporary = tempfile.mkstemp(prefix=dest.name + '.', dir=tdir)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, dest)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            print(target)
    except (RenderError, StateError, ValueError, OSError) as exc:
        print(f"render_handoff: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
