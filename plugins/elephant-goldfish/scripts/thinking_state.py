#!/usr/bin/env python3
"""thinking_state.py — deterministic state resolver for elephant-goldfish `thinking <topic>`.

The command needs the same handful of facts at every turn: which topics exist, which
phase this one is in, which artifacts are on disk, what was already published. Answering
that by `ls`-ing, `cat`-ing and `stat`-ing pulls directory listings and whole documents
into the model's context to recover a few dozen bytes of state. This script answers it in
one compact JSON blob instead — `resolve` is designed to be the single call the command
makes when it starts.

No network or model. Review receipts record evidence, not proof of human intent.

Usage:
  thinking_state.py list [--root DIR]
  thinking_state.py resolve <slug> [--root DIR]
  thinking_state.py init <slug> --output-type research|implementation
                    [--title TEXT] [--github issue|discussion|none] [--root DIR]
  thinking_state.py set <slug> KEY=VALUE [KEY=VALUE ...] [--root DIR]
  thinking_state.py gate <slug> --require discovery,spec [--root DIR]
  thinking_state.py review <slug> --decision accepted|owner_override --scope finalise-brief
                    --discovery-sha256 HASH --evidence-ref REF --operator-statement TEXT

`gate` is fail-closed: a missing artifact exits 1 and names it. Every other subcommand
prints JSON to stdout and exits 0, or prints a JSON error object and exits 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = "thinking"

# Source and final artifact filenames. Draft handoffs are deliberately separate.
ARTIFACTS = ("discovery.md", "spec.md", "handoff.md")

OUTPUT_TYPES = ("research", "implementation")
GITHUB_MODES = ("issue", "discussion", "none")

# Deliberately strict: this string becomes a directory name and is interpolated into
# `gh` arguments downstream. Anything with a dot, slash or space is rejected outright
# rather than sanitized, so a traversal attempt fails loudly instead of silently
# resolving somewhere unexpected.
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# The script's own CLI is unambiguous — a slug is always a positional after a subcommand, so
# `resolve list` reads fine. The ambiguity is one level up: `thinking <topic>` takes
# a bare `$ARGUMENTS` that is either the word `list` or a topic slug, and a topic actually
# named `list` makes that undecidable. Reserve the subcommand names so the collision cannot
# be created in the first place.
RESERVED_SLUGS = frozenset({"list", "resolve", "init", "set", "gate", "review"})
DRAFT_MARKER = "<!-- thinking:draft -->"
DRAFT_LABEL = "DRAFT. Non-executable."
REVIEW_SCOPE = "finalise-brief"


class StateError(Exception):
    """Anything the caller did wrong. Rendered as a JSON error object, exit 1."""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_slug(slug: str) -> str:
    if not SLUG_RE.fullmatch(slug or ""):
        raise StateError(
            f"invalid slug {slug!r}: use lowercase kebab-case, 1-63 chars, "
            "starting and ending alphanumeric (e.g. 'buy-family-car')"
        )
    if slug in RESERVED_SLUGS:
        raise StateError(
            f"slug {slug!r} is reserved — it collides with a subcommand name and would make "
            "the command's own argument ambiguous; pick another (e.g. 'list-topics')"
        )
    return slug


def topic_dir(root: Path, slug: str) -> Path:
    path = root / validate_slug(slug)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise StateError('topic directory escapes the requested root')
    return path


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def meta_path(tdir: Path) -> Path:
    return tdir / "meta.json"


def read_meta(tdir: Path) -> dict:
    mp = meta_path(tdir)
    if mp.is_symlink():
        raise StateError('topic metadata may not be a symlink')
    if not mp.exists():
        return {}
    try:
        meta = json.loads(mp.read_text(encoding="utf-8"))
        if not isinstance(meta, dict) or not isinstance(meta.get("published", {}), dict):
            raise StateError("topic metadata and published must be objects")
        return meta
    except json.JSONDecodeError as exc:
        raise StateError(f"{mp} is not valid JSON: {exc}") from exc


def write_meta(tdir: Path, meta: dict) -> None:
    """Replace meta.json atomically: a crash or full disk mid-write leaves the previous
    file intact rather than a truncated one that every later `resolve` rejects."""
    mp = meta_path(tdir)
    if mp.is_symlink():
        raise StateError('topic metadata may not be a symlink')
    meta["updated_at"] = utcnow()
    tdir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(meta, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=mp.name + ".", dir=tdir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, mp)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def artifact_state(tdir: Path, meta: dict) -> dict:
    """Per-artifact existence, digest and publish status.

    `published` compares the artifact's current digest against the digest recorded when
    it was last posted to GitHub. That makes republish decisions idempotent *and*
    correctly re-flags a doc that was edited after publishing, which an exists-only flag
    would miss.
    """
    published = meta.get("published", {})
    out = {}
    for name in ARTIFACTS:
        path = tdir / name
        if path.is_symlink():
            raise StateError(f'topic artifact may not be a symlink: {name}')
        if not path.exists():
            out[name] = {"exists": False}
            continue
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        text = content.decode("utf-8")
        out[name] = {
            "exists": True,
            "sha256": digest,
            "bytes": len(content),
            "published": published.get(name) == digest,
            "nonempty": bool(text.strip()),
            "draft": is_draft(text),
        }
    return out


def is_draft(text: str) -> bool:
    """Recognise standalone status lines, leaving quoted/fenced examples inert."""
    fence = None
    for line in text.lstrip("\ufeff").splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if match:
            run, suffix = match.groups()
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not suffix.strip():
                fence = None
            continue
        if fence is None and not line.startswith(("    ", "\t")):
            if line.strip() in (DRAFT_MARKER, DRAFT_LABEL):
                return True
    return False


def review_state(meta: dict, artifacts: dict) -> dict:
    """Validate a content-bound receipt. Its evidence still needs human inspection."""
    receipt = meta.get("review")
    reason = "missing operator discovery review evidence"
    if receipt is not None:
        reason = "malformed operator discovery review evidence"
        if (isinstance(receipt, dict) and type(receipt.get("schema")) is int and receipt["schema"] == 1
                and receipt.get("status") in ("accepted", "owner_override")
                and receipt.get("scope") == REVIEW_SCOPE
                and all(isinstance(receipt.get(key), str) and receipt[key].strip()
                        for key in ("evidence_ref", "operator_statement", "recorded_at"))
                and valid_timestamp(receipt["recorded_at"])
                and re.fullmatch(r"[a-f0-9]{64}", str(receipt.get("discovery_sha256", "")))):
            reason = "discovery changed since operator review"
            discovery = artifacts.get("discovery.md", {})
            if discovery.get("nonempty") and receipt["discovery_sha256"] == discovery.get("sha256"):
                return {"ready": True, "status": receipt["status"], "scope": REVIEW_SCOPE,
                        "reason": None, "execution_authorized": False}
    return {"ready": False, "status": "review_needed", "reason": reason,
            "execution_authorized": False}


def valid_timestamp(value: str) -> bool:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%dT%H:%M:%SZ") == value
    except ValueError:
        return False


def handoff_problem(tdir: Path, meta: dict, *, draft: bool = False) -> str | None:
    """Provenance only. Discovery review is checked independently by readiness."""
    stem = "handoff.draft" if draft else "handoff"
    try:
        path = tdir / f"{stem}.manifest.json"
        if path.is_symlink():
            return "handoff manifest may not be a symlink"
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or saved.get("schema") != 2:
            return "missing or legacy handoff provenance; re-render"
        expected = {"topic": tdir.name, "output_type": meta.get("output_type"),
                    "status": "draft" if draft else "final",
                    "requirement_ids": list(dict.fromkeys(re.findall(
                        r"\[(REQ-[A-Z0-9_-]+)\]", (tdir / "spec.md").read_text(encoding="utf-8"))))}
        for field, value in expected.items():
            if saved.get(field) != value:
                return "handoff provenance mismatch; re-render"
        for field, filename in (("discovery_sha256", "discovery.md"),
                                ("spec_sha256", "spec.md"), ("handoff_sha256", f"{stem}.md")):
            source = tdir / filename
            if source.is_symlink() or saved.get(field) != sha256_of(source):
                return "handoff provenance mismatch; re-render"
    except (OSError, ValueError):
        return "missing or malformed handoff provenance; re-render"
    return None


def phase_state(tdir: Path, meta: dict, artifacts: dict) -> dict:
    review = review_state(meta, artifacts)
    phase, reason = "complete", None
    if not artifacts["discovery.md"].get("nonempty"):
        phase, reason = "discovery", "missing or empty discovery.md"
    elif artifacts["discovery.md"].get("draft"):
        phase, reason = "discovery", "draft discovery.md must be finalised and reviewed"
    elif not review["ready"]:
        phase, reason = "discovery_review", review["reason"]
    elif not artifacts["spec.md"].get("nonempty") or artifacts["spec.md"].get("draft"):
        phase, reason = "spec", "missing, empty, or draft spec.md"
    elif not artifacts["handoff.md"].get("nonempty") or artifacts["handoff.md"].get("draft"):
        phase, reason = "handoff", "missing, empty, or draft handoff.md"
    else:
        reason = handoff_problem(tdir, meta)
        if reason:
            phase = "handoff"
    return {"next_phase": phase, "hold_reason": reason, "review": review,
            "workflow": "thinking", "execution_authorized": False,
            "has_execution_request": "execution_request" in meta}


def resolve(root: Path, slug: str) -> dict:
    tdir = topic_dir(root, slug)
    meta = read_meta(tdir)
    artifacts = artifact_state(tdir, meta)
    return {
        "slug": slug,
        "root": str(root),
        "dir": str(tdir),
        "exists": tdir.is_dir(),
        "meta": meta,
        "artifacts": artifacts,
        **phase_state(tdir, meta, artifacts),
    }


def cmd_list(args) -> dict:
    root = Path(args.root)
    topics = []
    if root.is_dir():
        for tdir in sorted(p for p in root.iterdir() if not p.is_symlink() and p.is_dir()):
            try:
                meta = read_meta(tdir)
                artifacts = artifact_state(tdir, meta)
                state = phase_state(tdir, meta, artifacts)
            except (StateError, UnicodeError, OSError) as exc:
                topics.append({"slug": tdir.name, "title": tdir.name, "output_type": None,
                               "next_phase": "topic_repair", "hold_reason": f"malformed topic: {exc}",
                               "workflow": "thinking", "execution_authorized": False,
                               "review": {"ready": False, "status": "review_needed"}})
                continue
            topics.append(
                {
                    "slug": tdir.name,
                    "title": meta.get("title", tdir.name),
                    "output_type": meta.get("output_type"),
                    **state,
                    "updated_at": meta.get("updated_at"),
                }
            )
    return {"root": str(root), "topics": topics}


def cmd_resolve(args) -> dict:
    return resolve(Path(args.root), args.slug)


def cmd_init(args) -> dict:
    root = Path(args.root)
    tdir = topic_dir(root, args.slug)
    if args.output_type not in OUTPUT_TYPES:
        raise StateError(f"--output-type must be one of {'|'.join(OUTPUT_TYPES)}, got {args.output_type!r}")
    if args.github not in GITHUB_MODES:
        raise StateError(f"--github must be one of {'|'.join(GITHUB_MODES)}, got {args.github!r}")

    meta = read_meta(tdir)
    if meta:
        # Re-running init on a live topic must not silently reset output_type or drop the
        # published map — the command uses this path to resume, not to restart.
        raise StateError(
            f"topic {args.slug!r} already initialised; "
            "use `set` to change fields, or pick a different slug"
        )

    meta = {
        "slug": args.slug,
        "title": args.title or args.slug.replace("-", " "),
        "output_type": args.output_type,
        "created_at": utcnow(),
        "github": {"mode": args.github, "repo": None, "number": None, "url": None, "category": None},
        "published": {},
    }
    write_meta(tdir, meta)
    return resolve(root, args.slug)


def set_dotted(meta: dict, key: str, value):
    # `published` is the one map in the schema whose keys are filenames, so they contain
    # dots and cannot survive this splitter: `published.discovery.md` would nest into
    # {"published": {"discovery": {"md": ...}}}, which no lookup would ever match and no
    # error would ever report — every publish check silently false, forever. Refuse the
    # whole prefix rather than special-casing it; gh_publish.py owns that map anyway.
    if key == "published" or key.startswith("published."):
        raise StateError(
            "refusing to set 'published' through `set`: its keys are filenames containing "
            "dots, which this dotted-key syntax cannot address. gh_publish.py maintains it."
        )
    if key == "review" or key.startswith("review."):
        raise StateError("use `review` to record operator evidence; `set` cannot grant review")
    parts = key.split(".")
    cursor = meta
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
        if not isinstance(cursor, dict):
            raise StateError(f"cannot set {key!r}: {part!r} is not an object")
    cursor[parts[-1]] = value


def coerce(raw: str):
    """JSON-first so `--` callers can pass numbers, null and booleans; bare words stay strings."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def cmd_set(args) -> dict:
    root = Path(args.root)
    tdir = topic_dir(root, args.slug)
    meta = read_meta(tdir)
    if not meta:
        raise StateError(f"no topic {args.slug!r} under {root} — run `init` first")
    for pair in args.pairs:
        if "=" not in pair:
            raise StateError(f"expected KEY=VALUE, got {pair!r}")
        key, raw = pair.split("=", 1)
        set_dotted(meta, key.strip(), coerce(raw))
    write_meta(tdir, meta)
    return resolve(root, args.slug)


def cmd_review(args) -> dict:
    root = Path(args.root)
    tdir = topic_dir(root, args.slug)
    meta = read_meta(tdir)
    if not meta:
        raise StateError("initialise the topic before recording review")
    artifacts = artifact_state(tdir, meta)
    discovery = artifacts["discovery.md"]
    if not discovery.get("nonempty"):
        raise StateError("missing or empty discovery.md")
    if discovery.get("draft"):
        raise StateError("draft discovery.md must be finalised before recording operator review")
    if args.discovery_sha256 != discovery["sha256"]:
        raise StateError("reviewed discovery hash differs from current discovery.md")
    statement = args.operator_statement
    if args.operator_statement_file is not None:
        statement = (sys.stdin.read() if args.operator_statement_file == "-"
                     else Path(args.operator_statement_file).read_bytes().decode("utf-8"))
    if not args.evidence_ref.strip() or not statement.strip():
        raise StateError("operator statement and source reference must be nonempty")
    meta["review"] = {"schema": 1, "status": args.decision, "scope": args.scope,
                      "discovery_sha256": args.discovery_sha256,
                      "evidence_ref": args.evidence_ref,
                      "operator_statement": statement, "recorded_at": utcnow()}
    write_meta(tdir, meta)
    return resolve(root, args.slug)


def cmd_gate(args) -> dict:
    """Fail-closed artifact gate. Missing or empty input is an error, never a warning.

    Existence alone is too weak a check: a 0-byte discovery.md is an interrupted phase, not
    a completed one, and letting it through means the failure surfaces later in
    render_handoff.py — the wrong component, with a worse message, after the gate has
    already reported "pass".
    """
    root = Path(args.root)
    tdir = topic_dir(root, args.slug)
    required = [r.strip() for r in args.require.split(",") if r.strip()]
    if not required:
        raise StateError('at least one known artifact is required')
    names = [req if req.endswith('.md') else f'{req}.md' for req in required]
    if any(name not in ARTIFACTS for name in names):
        raise StateError('required artifacts must be discovery, spec, or handoff')
    missing, empty = [], []
    for name in names:
        path = tdir / name
        if path.is_symlink():
            raise StateError(f'topic artifact may not be a symlink: {name}')
        if not path.exists():
            missing.append(name)
        elif not path.read_text(encoding="utf-8").strip():
            empty.append(name)
    if missing or empty:
        problems = []
        if missing:
            problems.append(f"missing: {', '.join(missing)}")
        if empty:
            problems.append(f"empty: {', '.join(empty)}")
        raise StateError(
            f"topic {args.slug!r} is not ready ({'; '.join(problems)}) — "
            "run the earlier phase before this one"
        )
    meta = read_meta(tdir)
    artifacts = artifact_state(tdir, meta)
    if not args.draft:
        review = review_state(meta, artifacts)
        if not review["ready"]:
            raise StateError(review["reason"])
        if any(artifacts[name].get("draft") for name in set(names) | {"discovery.md"}):
            raise StateError("draft artifacts cannot pass final readiness")
        if "handoff.md" in names:
            problem = handoff_problem(tdir, meta)
            if problem:
                raise StateError(problem)
    return {"slug": args.slug, "gate": "draft" if args.draft else "pass", "required": required,
            "review": review_state(meta, artifacts),
            "input_hashes": {name: state.get("sha256") for name, state in artifacts.items()},
            "execution_authorized": False}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="thinking_state.py", description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=DEFAULT_ROOT, help=f"topics directory (default: {DEFAULT_ROOT})")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list all topics")

    p_resolve = sub.add_parser("resolve", help="full state for one topic")
    p_resolve.add_argument("slug")

    p_init = sub.add_parser("init", help="create a topic")
    p_init.add_argument("slug")
    p_init.add_argument("--output-type", required=True, choices=OUTPUT_TYPES)
    p_init.add_argument("--title", default=None)
    p_init.add_argument("--github", default="none", choices=GITHUB_MODES)

    p_set = sub.add_parser("set", help="update meta fields (dotted keys allowed)")
    p_set.add_argument("slug")
    p_set.add_argument("pairs", nargs="+", metavar="KEY=VALUE")

    p_review = sub.add_parser("review", help="record actual operator evidence for a reviewed hash")
    p_review.add_argument("slug")
    p_review.add_argument("--decision", choices=("accepted", "owner_override"), required=True)
    p_review.add_argument("--scope", choices=(REVIEW_SCOPE,), required=True)
    p_review.add_argument("--discovery-sha256", required=True)
    p_review.add_argument("--evidence-ref", required=True)
    statement = p_review.add_mutually_exclusive_group(required=True)
    statement.add_argument("--operator-statement", help="literal statement; prefer a file for shell calls")
    statement.add_argument("--operator-statement-file", help="UTF-8 statement file, or - for stdin")

    p_gate = sub.add_parser("gate", help="check artifacts and operator discovery review")
    p_gate.add_argument("slug")
    p_gate.add_argument("--require", required=True, help="comma-separated artifact names")
    p_gate.add_argument("--draft", action="store_true", help="check draft inputs without final readiness")

    return parser


HANDLERS = {
    "list": cmd_list,
    "resolve": cmd_resolve,
    "init": cmd_init,
    "set": cmd_set,
    "gate": cmd_gate,
    "review": cmd_review,
}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = HANDLERS[args.cmd](args)
    except (StateError, OSError, UnicodeError) as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
