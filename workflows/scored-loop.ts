// @tested-t3 0.1.12-nightly.20261123.5151
// @start manual
//
// Durable bookkeeping for skills/review-loop/SKILL.md and skills/hillclimb/SKILL.md
// (`skill` in the packet): reviewer selection or the confirmed roster, the frozen
// candidate, the score, the target, check and coverage gate, the
// two-non-improving-rounds stop, one retry of a failed evaluation, explicit
// limits, required-fix eligibility, the single automatic recovery and the score
// ledger. Hillclimb adds the panel phase (skills/hillclimb/references/rounds.md):
// the confirmed panel joins when the primary gate passes, or at the baseline, and
// the lowest judge score is the metric from then on. Judgment stays in agent steps:
// each judge scores in a fresh thread; the invoking thread repairs, reports receipts
// and limits, and diagnoses the recovery.
//
// Fewer bookkeeping turns: the start packet carries the first route report
// (`startReport`), and a repair turn also returns the host receipts for the judges
// that scored the candidate it repairs. A receipt naming another model voids that
// round's score, never the repair. Before any decision a repair turn cannot carry
// (panel entry, acceptance or a stop), the receipts are read in their own turn.
// Scores round to `scale.decimals` places. A continuation carries the prior run's
// ledger (`continuation.priorLedger`), so the score ledger covers the whole run family.
//
// One rule guards every limit: `limits()` runs as a journaled step before each
// dispatch and after each result the invoking thread returns. It stops the run
// when the deadline has passed or the spend cap is reported reached, and a judge
// dispatches only to a route the latest invoker report lists as available. A
// result observed after the deadline never counts.
//
// Start: POST a JSON packet to this workflow's `start` webhook with an
// `idempotency-key` header; the same key returns the same run. The hook URL lives
// in a private curl config; never put it in a command line, a transcript or this file.
//
// At-most-once dispatch (REC-01): every judge, repair and recovery dispatch is a
// keyed agent step. T3 journals each start under `<run>/<step>/<round>` and derives
// the turn from that key, so a restart or reload replays the recorded turn
// instead of starting another. The recovery has one step key per run, and a
// continuation packet carries the spent slot, so no run family gets two. A repair
// turn the operator cancels is sent once more under `<round>/repair/resume`,
// charging no second round; any other failure, or a second one, stops the run.

const MODES = ["approval-required", "auto-accept-edits", "auto", "full-access"];
const MODE_RANK = { "approval-required": 0, "auto-accept-edits": 1, auto: 2, "full-access": 3 };

// Review's standing routes (model-selection.md). Grok 4.7 is in that order but has no
// verified T3 route on the tested host (#325); selection reports it as a gate.
const ROUTES = {
  sol: { label: "Sol 6.2 high", instanceId: "codex", model: "gpt-6.2-sol", effort: { id: "reasoningEffort", value: "high" }, lineage: "openai", version: "6.2" },
  opus: { label: "Opus 5.5 high", instanceId: "claudeAgent", model: "claude-opus-5-5", effort: { id: "effort", value: "high" }, lineage: "anthropic", version: "5.5" },
  "sonnet-agy": { label: "Sonnet 5.5 high via AGY", instanceId: "antigravity", model: "claude-sonnet-5-5", effort: { id: "thought_level", value: "high" }, lineage: "anthropic", version: "5.5", minMode: "auto-accept-edits" },
  neon: { label: "Neon 4 high", instanceId: "antigravity", model: "gemini-4-neon", effort: { id: "thought_level", value: "high" }, lineage: "google", version: "4", minMode: "auto-accept-edits" },
  hydrogen: { label: "Hydrogen 4 high", instanceId: "antigravity", model: "gemini-4-hydrogen", effort: { id: "thought_level", value: "high" }, lineage: "google", version: "4", minMode: "auto-accept-edits" },
  // Hillclimb scoring only (skills/hillclimb/references/judges.md); never a review-loop reviewer.
  "deepseek-flash": { label: "DeepSeek Flash 4.1 high", instanceId: "opencode", model: "litellm/deepseek-v4.1-flash", aliases: ["deepseek-v4.1-flash"], effort: { id: "variant", value: "high" }, lineage: "deepseek", version: "4.1", minMode: "full-access", scoringOnly: true },
};
const ROUTE_KEYS = Object.keys(ROUTES);
const STATIC_ORDER = ["sol", "opus", "sonnet-agy", "neon", "hydrogen"];
const LINEAGES = ["anthropic", "openai", "google", "deepseek", "xai", "qwen", "other"];
const SEVERITIES = ["SEV1", "SEV2", "SEV3"];
const CARD = `${process.env.HOME}/.agents/skills/review/references/assigned-reviewer.md`;
const NO_DEADLINE = Number.POSITIVE_INFINITY;
// The judge brief's version, part of every evaluation fingerprint: raise it when the brief changes
// what a judge scores or reports, so earlier scores are never reused or charted as comparable.
const JUDGE_BRIEF = "judge-brief-2";
// Hillclimb judges list at most this many findings: the issues that most affected the score.
const FINDINGS_CAP = 10;
// The reason T3 gives when the operator stops an agent turn (observed in a run on 25 Nov 2026).
const CANCELLED = /turn was stopped: cancelled/i;

// Words that name a model family, sibling models inside a family, and effort settings,
// for checking a judge's own identity claim against its route.
const FAMILY_WORDS = {
  openai: ["gpt", "sol", "openai", "codex", "chatgpt"],
  anthropic: ["claude", "opus", "sonnet", "fable", "haiku", "anthropic"],
  google: ["gemini", "neon", "hydrogen", "argon", "carbon", "google"],
  deepseek: ["deepseek"],
  xai: ["grok", "xai"],
  qwen: ["qwen"],
};
const SIBLINGS = {
  sol: ["terra", "luna", "astra"],
  opus: ["sonnet", "haiku", "fable"],
  "sonnet-agy": ["opus", "haiku", "fable"],
  neon: ["hydrogen", "argon", "carbon", "flash"],
  hydrogen: ["neon", "argon", "carbon", "flash"],
  "deepseek-flash": ["pro", "reasoner"],
};
const EFFORT_WORDS = ["minimal", "low", "medium", "high", "xhigh", "max", "ultra", "ultrathink"];

// ---------- schemas ----------

const Checks = Schema.Struct({ passed: Schema.Boolean, coverage: Schema.Boolean, summary: Schema.String });
const Route = Schema.Literals(ROUTE_KEYS);

const Test = Schema.Struct({
  // One row per scoring judge attempt, in order (seats in roster order within an evaluation, then
  // its retries): the score, or null for a failure.
  scores: Schema.Array(Schema.NullOr(Schema.Number)),
  // Repair numbers (1-based, across the run) whose synthetic result has these properties.
  failChecks: Schema.optional(Schema.Array(Schema.Number)),
  unbuildable: Schema.optional(Schema.Array(Schema.Number)),
  requiredFix: Schema.optional(Schema.Array(Schema.Number)),
  resubmit: Schema.optional(Schema.Array(Schema.Number)),
  capAfterRepair: Schema.optional(Schema.Number),
  // Evaluations (1-based) whose judge reports a coverage gap.
  coverageGap: Schema.optional(Schema.Array(Schema.Number)),
  // A synthetic recovery; leave it out to ask the invoking thread for a real one.
  recovery: Schema.optional(Schema.Struct({
    outcome: Schema.Literals(["fixed", "fix-failed"]),
    target: Schema.optional(Schema.Number),
    changes: Schema.optional(Schema.Boolean),
  })),
  pauseAt: Schema.optional(Schema.Array(Schema.Literals(["before-recovery", "after-recovery", "after-baseline"]))),
  pauseSeconds: Schema.optional(Schema.Number),
});

// Every invoker turn reports, from orchestrator_capabilities, the routes it verified as available
// (exact model and effort option), and whether the spend cap is reached.
const Report = {
  availableRoutes: Schema.Array(Schema.String),
  spendCapReached: Schema.Boolean,
};
const PaceRow = Schema.Struct({
  provider: Schema.String,
  paceScore: Schema.NullOr(Schema.Number),
  paceBasis: Schema.NullOr(Schema.String),
});
// The invoker's report at launch, inside the packet: routes, spend cap and, when the limits tool
// exists in its session, each provider's pace.
const StartReport = Schema.Struct({
  ...Report,
  observedAt: Schema.String,
  providers: Schema.optional(Schema.Array(PaceRow)),
});
const ReceiptRow = Schema.Struct({
  thread: Schema.String,
  turnId: Schema.NullOr(Schema.String),
  executedModel: Schema.NullOr(Schema.String),
  turns: Schema.NullOr(Schema.Number),
});
const Finding = Schema.Struct({
  id: Schema.String,
  severity: Schema.Literals(SEVERITIES),
  title: Schema.String,
  location: Schema.String,
  evidence: Schema.String,
  impact: Schema.String,
});
// A score ledger as the chart reads it (skills/review/references/score-chart.md); eras and rounds
// pass through unchanged.
const PriorLedger = Schema.Struct({
  run: Schema.Struct({ id: Schema.String, scale: Schema.Struct({ min: Schema.Number, max: Schema.Number, precision: Schema.Number }) }),
  reviewers: Schema.Array(Schema.Struct({ id: Schema.String, label: Schema.String, role: Schema.optional(Schema.String) })),
  eras: Schema.Array(Schema.Unknown),
  rounds: Schema.Array(Schema.Unknown),
});

const Packet = Schema.Struct({
  // The skill whose rules apply; review-loop when absent.
  skill: Schema.optional(Schema.Literals(["review-loop", "hillclimb"])),
  invokerThread: Schema.String,
  title: Schema.String,
  // T3 project ID or registered path for the judge thread; the judge reads the checkout by path.
  project: Schema.String,
  maxRuntimeMode: Schema.Literals(MODES),
  scope: Schema.Literals(["code", "plan", "prose", "visual"]),
  checkout: Schema.String,
  base: Schema.String,
  candidate: Schema.String,
  checks: Checks,
  criteria: Schema.String,
  rubric: Schema.String,
  target: Schema.Number,
  // Scores round to `decimals` places (0 to 3; one when absent). The retired `precision` field is
  // declared only so a packet still using it is rejected by name instead of silently dropped.
  scale: Schema.Struct({ min: Schema.Number, max: Schema.Number, decimals: Schema.optional(Schema.Number), precision: Schema.optional(Schema.Number) }),
  // The invoker's route report at launch; required outside test runs.
  startReport: Schema.optional(StartReport),
  // Model families that materially wrote the code, repairers included.
  codeAuthors: Schema.Array(Schema.Literals(LINEAGES)),
  // Permitted checks, commands, scratch directory and evidence requirements for the judge.
  reviewContext: Schema.String,
  // Only when the user named the primary reviewer; otherwise the workflow selects it.
  primary: Schema.optional(Route),
  // A reviewer the user explicitly named outside the standing routes (model-selection.md rule 3),
  // with its exact host route and effort. It becomes the primary.
  namedReviewer: Schema.optional(Schema.Struct({
    label: Schema.String,
    instanceId: Schema.String,
    model: Schema.String,
    effort: Schema.Struct({ id: Schema.String, value: Schema.String }),
    lineage: Schema.Literals(LINEAGES),
    version: Schema.String,
  })),
  // Finding-only companions, such as Hydrogen for visual scope.
  companions: Schema.optional(Schema.Array(Route)),
  // Hillclimb's confirmed panel (required for hillclimb; `judges: []` is a confirmed primary-only run).
  // The primary scores alone until `trigger`; then the primary, or the preapproved `panelPrimary`,
  // and every judge score each candidate together.
  panel: Schema.optional(Schema.Struct({
    judges: Schema.Array(Route),
    trigger: Schema.Literals(["primary-pass", "baseline"]),
    panelPrimary: Schema.optional(Route),
  })),
  // Hillclimb: operator-confirmed alternate routes authorised for the single automatic recovery.
  alternates: Schema.optional(Schema.Array(Route)),
  // Hillclimb: the operator's recorded approval of a disclosed lineage overlap among scorers and implementers.
  overlapApproval: Schema.optional(Schema.String),
  limits: Schema.optional(Schema.Struct({
    repairRounds: Schema.optional(Schema.Number),
    deadline: Schema.optional(Schema.String),
    // As the operator stated it; the invoking thread reports reaching it.
    spendCap: Schema.optional(Schema.String),
  })),
  // An operator-approved continuation of a stopped run: its automatic recovery is spent.
  continuation: Schema.optional(Schema.Struct({
    priorRun: Schema.String,
    repairsUsed: Schema.Number,
    approval: Schema.String,
    // The approved changed approach, for the ledger's continuation marker.
    change: Schema.optional(Schema.String),
    // The prior run's final score ledger (its result's `ledger`), so the chart covers every run.
    priorLedger: Schema.optional(PriorLedger),
    // A valid prior score for this exact candidate under this exact contract and roster, reused
    // instead of judging unchanged work again (budget-exhaustion.md, approved continuation step 2).
    // Copy it from the prior result's `continueWith.baseline`; reuse also needs a matching fingerprint.
    baseline: Schema.optional(Schema.Struct({
      primary: Schema.String,
      score: Schema.Number,
      bullets: Schema.Array(Schema.String),
      judgeThread: Schema.String,
      candidate: Schema.optional(Schema.String),
      fingerprint: Schema.optional(Schema.String),
      coverageComplete: Schema.optional(Schema.Boolean),
      findings: Schema.optional(Schema.Array(Finding)),
    })),
  })),
  // The project adopted `review_rounds: 1` (skills/review/references/single-round.md).
  singleRound: Schema.optional(Schema.Boolean),
  judgeMinutes: Schema.optional(Schema.Number),
  repairMinutes: Schema.optional(Schema.Number),
  test: Schema.optional(Test),
});
const decodePacket = Schema.decodeUnknownSync(Packet);

const Receipts = Schema.Struct({
  ...Report,
  judges: Schema.Array(ReceiptRow),
});
const Judged = Schema.Struct({
  revision: Schema.String,
  score: Schema.NullOr(Schema.Number),
  bullets: Schema.Array(Schema.String),
  dimensions: Schema.optional(Schema.Array(Schema.Struct({ name: Schema.String, score: Schema.Number, weight: Schema.optional(Schema.Number) }))),
  findings: Schema.Array(Finding),
  // Hillclimb: the judge's verdict on each of its findings on the previous candidate.
  rechecks: Schema.optional(Schema.Array(Schema.Struct({ id: Schema.String, status: Schema.Literals(["fixed", "open"]), evidence: Schema.String }))),
  coverageComplete: Schema.Boolean,
  coverageGaps: Schema.String,
  model: Schema.String,
});
const Repair = Schema.Struct({
  ...Report,
  candidate: Schema.String,
  checks: Checks,
  buildable: Schema.Boolean,
  addsRequiredFix: Schema.Boolean,
  summary: Schema.String,
  dispositions: Schema.Array(Schema.Struct({
    id: Schema.String,
    disposition: Schema.Literals(["fixed", "deferred", "rejected", "open"]),
    note: Schema.String,
  })),
  stop: Schema.NullOr(Schema.Struct({ reason: Schema.String, limit: Schema.Literals(["none", "spend-cap", "deadline"]) })),
  verification: Schema.NullOr(Schema.Struct({ verified: Schema.Boolean, summary: Schema.String })),
  // Host receipts for the judge threads the turn lists (none listed: leave it out or empty).
  judges: Schema.optional(Schema.Array(ReceiptRow)),
});
const Fix = Schema.Struct({
  ...Report,
  outcome: Schema.Literals(["fixed", "fix-failed"]),
  diagnosis: Schema.String,
  fix: Schema.String,
  candidate: Schema.String,
  checks: Checks,
  buildable: Schema.Boolean,
  addsRequiredFix: Schema.Boolean,
  revised: Schema.NullOr(Schema.Struct({
    reason: Schema.String,
    target: Schema.optional(Schema.Number),
    rubric: Schema.optional(Schema.String),
    criteria: Schema.optional(Schema.String),
    checks: Schema.optional(Schema.String),
    primary: Schema.optional(Route),
    panel: Schema.optional(Schema.Array(Route)),
  })),
});

// ---------- pure rules (no clock, no I/O) ----------

// Decimal places scores round to: the packet's and the ledger's unit alike.
const decimalsOf = (scale) => scale.decimals ?? 1;

// The rubric's fixed precision, rounded half up and kept inside the scale. The small epsilon keeps
// binary fractions such as 8.15 from rounding down.
function quantise(score, scale) {
  const f = 10 ** decimalsOf(scale);
  const stepped = Number((Math.round(score * f + 1e-9) / f).toFixed(decimalsOf(scale)));
  return Math.min(scale.max, Math.max(scale.min, stepped));
}

// A score or target as the rubric shows it ("8.0", not "8").
const fmt = (value, scale) => (typeof value === "number" ? value.toFixed(decimalsOf(scale)) : "none");

// FNV-1a over the text, twice with different seeds: a stable 16-hex-digit fingerprint.
function hashText(text) {
  const one = (seed) => {
    let h = seed >>> 0;
    for (let i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h.toString(16).padStart(8, "0");
  };
  return one(2166136261) + one(3735928559);
}

// A finding id without the route prefixes the repair brief adds (`sol/sol/ID` came from judges
// reusing the prefixed ids they were shown).
const bareId = (key, id) => String(id).replace(new RegExp(`^(?:${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/)+`), "");

// A judge runs in the invoker's own mode, as a delegated reviewer inherits it; a route that
// needs a broader mode is skipped.
function modeOf(route, ceiling) {
  return route.minMode !== undefined && MODE_RANK[route.minMode] > MODE_RANK[ceiling] ? null : ceiling;
}

function sameRevision(a, b) {
  const x = String(a ?? "").trim().toLowerCase();
  const y = String(b ?? "").trim().toLowerCase();
  return x.length >= 7 && y.length >= 7 && (x.startsWith(y) || y.startsWith(x));
}

const skillOf = (p) => p.skill ?? "review-loop";

// Review-loop's hard code-author gate. Hillclimb scorers have none: a disclosed overlap needs the
// operator's approval instead (rosterOverlaps).
function lineageBlocked(p, key) {
  return skillOf(p) === "review-loop" && p.scope === "code" && p.codeAuthors.includes(ROUTES[key].lineage);
}

function executedMatches(route, model) {
  const actual = String(model).trim().toLowerCase();
  return [route.model, ...(route.aliases ?? [])].some((m) => m.toLowerCase() === actual);
}

// Concurrent scorer groups: the primary alone, plus the panel set when judges are configured.
// Primary and panelPrimary never score together because panel entry swaps primary for panelPrimary.
function scorerGroups(primary, panelPrimary, judges) {
  const groups = [];
  if (primary !== null) groups.push([primary]);
  if (judges.length > 0) {
    const lead = panelPrimary ?? primary;
    groups.push([...(lead !== null ? [lead] : []), ...judges]);
  }
  return groups;
}

function uniqueScorers(groups) {
  const seen = new Set();
  const out = [];
  for (const group of groups) {
    for (const s of group) {
      if (!seen.has(s.name)) {
        seen.add(s.name);
        out.push(s);
      }
    }
  }
  return out;
}

// Hillclimb overlaps between any scorer and implementers, and between scorers that judge together
// (judges.md step 3). `groups` is a list of concurrent scorer groups of { name, lineage }.
function rosterOverlaps(p, groups) {
  const out = [];
  for (const s of uniqueScorers(groups)) {
    if (p.codeAuthors.includes(s.lineage)) out.push(`${s.name} shares the ${s.lineage} lineage with an implementer`);
  }
  const paired = new Set();
  for (const group of groups) {
    group.forEach((s, i) => {
      for (const t of group.slice(i + 1)) {
        if (t.lineage === s.lineage) {
          const pairKey = [s.name, t.name].sort().join("\0");
          if (!paired.has(pairKey)) {
            paired.add(pairKey);
            out.push(`${s.name} and ${t.name} share the ${s.lineage} lineage`);
          }
        }
      }
    });
  }
  return out;
}

// The kinds of overlap a roster has ("implementer:<lineage>", "pair:<lineage>"): a replacement that
// adds a kind needs new approval.
function overlapKinds(p, groups) {
  const kinds = new Set();
  for (const s of uniqueScorers(groups)) {
    if (p.codeAuthors.includes(s.lineage)) kinds.add(`implementer:${s.lineage}`);
  }
  for (const group of groups) {
    group.forEach((s, i) => {
      if (group.slice(i + 1).some((t) => t.lineage === s.lineage)) kinds.add(`pair:${s.lineage}`);
    });
  }
  return kinds;
}

// True when hillclimb's panel starts at the baseline with a panelPrimary, swapping the original
// primary out before any score so it never runs.
function isBaselineSwap(p) {
  return skillOf(p) === "hillclimb" && (p.panel?.judges ?? []).length > 0
    && p.panel?.trigger === "baseline" && p.panel?.panelPrimary !== undefined;
}

// The concurrent hillclimb scorer groups a packet confirms. When the panel starts at the baseline
// with a panelPrimary, enterPanel swaps primary for panelPrimary before any score, so primary never scores.
function packetScorerGroups(p) {
  const judges = (p.panel?.judges ?? []).map((k) => ({ name: k, lineage: ROUTES[k].lineage }));
  const up = judges.length > 0 && p.panel?.panelPrimary !== undefined
    ? { name: p.panel.panelPrimary, lineage: ROUTES[p.panel.panelPrimary].lineage } : null;
  const first = isBaselineSwap(p) ? null
    : p.namedReviewer ? { name: p.namedReviewer.label, lineage: p.namedReviewer.lineage }
    : p.primary ? { name: p.primary, lineage: ROUTES[p.primary].lineage } : null;
  return scorerGroups(first, up, judges);
}

// On the scale's decimal grid, checked without clamping to the scale.
function onGrid(scale, value) {
  const f = 10 ** decimalsOf(scale);
  return Math.abs(Math.round(value * f) / f - value) < 1e-9;
}

// An accepted target, stored exactly as the grid value it displays as (0.1 + 0.2 becomes 0.3).
const gridValue = (scale, value) => Number((Math.round(value * 10 ** decimalsOf(scale)) / 10 ** decimalsOf(scale)).toFixed(decimalsOf(scale)));

// Inside the scale and on its decimal grid, so a target never displays as a score it does not equal.
function targetFits(scale, target) {
  return typeof target === "number" && Number.isFinite(target) && target > scale.min && target <= scale.max && onGrid(scale, target);
}

const validDecimals = (scale) => scale.decimals === undefined || (Number.isInteger(scale.decimals) && scale.decimals >= 0 && scale.decimals <= 3);

// A prior round's id in the merged ledger: prefixed once with its run's id.
const mergedRoundId = (prior, id) => {
  const own = String(id).trim();
  return own.includes(":") ? own : `${String(prior.run.id).trim().slice(0, 8)}:${own}`;
};

// The prior ledger, checked before any dispatch against the chart renderer's rules
// (skills/review/scripts/render_score_chart.py), so the merged ledger always renders.
function priorLedgerProblems(prior) {
  const problems = [];
  const obj = (x) => x !== null && typeof x === "object" && !Array.isArray(x);
  const text = (x) => typeof x === "string" && x.trim() !== "";
  const num = (x) => typeof x === "number" && Number.isFinite(x);
  // The renderer reads optional fields with a default only when they are absent; an explicit null fails.
  const or = (x, d) => (x === undefined ? d : x);
  const precision = prior.run.scale.precision;
  if (!(Number.isInteger(precision) && precision >= 0 && precision <= 3)) problems.push("continuation.priorLedger.run.scale.precision must be a whole number from 0 to 3");
  const { min, max } = prior.run.scale;
  const inScale = (x) => num(x) && x >= min && x <= max;
  const bool = (x) => typeof x === "boolean";
  // Ids compare as the renderer reads them: trimmed.
  const reviewerIds = new Set();
  prior.reviewers.forEach((r, i) => {
    const rid = text(r.id) ? r.id.trim() : null;
    if (rid === null || !text(r.label) || reviewerIds.has(rid) || !(r.role === undefined || r.role === null || typeof r.role === "string")) {
      problems.push(`continuation.priorLedger.reviewers[${i}] needs a unique id and a label`);
    }
    if (rid !== null) reviewerIds.add(rid);
  });
  if (reviewerIds.size === 0) problems.push("continuation.priorLedger needs its reviewers");
  const eraOrder = new Map();
  prior.eras.forEach((e, i) => {
    const eid = obj(e) && text(e.id) ? e.id.trim() : null;
    const rec = obj(e) ? e.recovery : undefined;
    const ok = eid !== null && !eraOrder.has(eid) && text(e.label) && inScale(e.target)
      && (e.original_target === undefined || e.original_target === null || inScale(e.original_target))
      && bool(or(e.historical, false)) && bool(or(e.comparable_to_prev, i > 0)) && typeof or(e.note, "") === "string"
      && (rec === undefined || rec === null || (obj(rec) && ["automatic", "continuation", "rebaseline"].includes(or(rec.kind, "automatic"))
        && [rec.label, rec.trigger, rec.diagnosis, rec.fix].every(text)));
    if (!ok) problems.push(`continuation.priorLedger.eras[${i}] needs a unique id, a label, a target inside the scale and valid flags`);
    else eraOrder.set(eid, i);
  });
  const roundIds = new Set();
  let last = -1;
  prior.rounds.forEach((r, i) => {
    const where = `continuation.priorLedger.rounds[${i}]`;
    const era = obj(r) && text(r.era) ? r.era.trim() : null;
    if (!obj(r) || !text(r.id) || !text(r.label) || era === null || !eraOrder.has(era) || eraOrder.get(era) < last
      || typeof or(r.candidate, "") !== "string") {
      problems.push(`${where} needs an id, a label and a known era in order`);
      return;
    }
    last = eraOrder.get(era);
    const merged = mergedRoundId(prior, r.id);
    if (roundIds.has(merged)) problems.push(`${where}: id ${r.id} collides with another round once prefixed as ${merged}`);
    roundIds.add(merged);
    const phase = or(r.phase, "primary");
    const status = or(r.status, "scored");
    if (!["primary", "panel", "review"].includes(typeof phase === "string" ? phase.trim() : phase)
      || !["scored", "unscored", "incomplete"].includes(typeof status === "string" ? status.trim() : status)) {
      problems.push(`${where} needs a known phase and status`);
    }
    const note = or(r.failure_note, "");
    if (typeof note !== "string" || (status !== "scored" && !text(note))) problems.push(`${where} needs a failure_note for its ${status} status`);
    const expected = Array.isArray(r.expected_reviewers) ? r.expected_reviewers : [];
    const trimmed = expected.map((x) => (text(x) ? x.trim() : null));
    if (trimmed.length === 0 || trimmed.includes(null) || new Set(trimmed).size !== trimmed.length || !trimmed.every((x) => reviewerIds.has(x))) {
      problems.push(`${where} needs distinct, known expected_reviewers`);
    }
    const scores = or(r.scores, []);
    const seen = new Set();
    for (const s of Array.isArray(scores) ? scores : [null]) {
      const who = obj(s) && text(s.reviewer) ? s.reviewer.trim() : null;
      const scoreOk = who !== null && reviewerIds.has(who) && !seen.has(who) && bool(or(s.retried, false))
        && (s.retried !== true || text(s.retry_note))
        && (s.score === null || s.score === undefined
          ? text(or(s.failure_note, note)) && text(or(s.status, "not-evaluated"))
          : inScale(s.score) && status !== "unscored" && Array.isArray(s.bullets) && s.bullets.length >= 3 && s.bullets.length <= 5 && s.bullets.every(text)
            && Array.isArray(or(s.dimensions, [])) && or(s.dimensions, []).every((d) => obj(d) && text(d.name) && inScale(d.score)
              && (d.weight === undefined || d.weight === null || (num(d.weight) && d.weight > 0))));
      if (!scoreOk) {
        problems.push(`${where} has a score the chart cannot draw (a known reviewer once; a number inside the scale with 3 to 5 bullets, or null with a failure note)`);
        break;
      }
      seen.add(who);
    }
  });
  return problems.slice(0, 6);
}

function packetProblems(p) {
  const problems = [];
  for (const field of ["invokerThread", "title", "project", "checkout", "base", "candidate", "criteria", "rubric"]) {
    if (!String(p[field]).trim()) problems.push(`${field} is empty`);
  }
  if (!p.checkout.startsWith("/")) problems.push("checkout must be an absolute path");
  const s = p.scale;
  if (s.precision !== undefined) {
    problems.push("scale.precision is retired: give scale.decimals, the number of decimal places scores round to (decimals: 1 for steps of 0.1)");
  }
  if (!(s.max > s.min)) problems.push("scale needs min < max");
  // Precision is checked first: the target's grid check depends on it.
  if (!validDecimals(s)) problems.push("scale.decimals must be a whole number from 0 to 3");
  else if (!targetFits(s, p.target)) problems.push(`target must sit inside the scale and on its ${decimalsOf(s)}-decimal grid`);
  if (p.test === undefined && p.startReport === undefined) {
    problems.push("startReport is required: report availableRoutes, spendCapReached, observedAt and any provider pace before starting");
  }
  if (p.primary !== undefined && lineageBlocked(p, p.primary)) {
    problems.push(`${p.primary} shares the ${ROUTES[p.primary].lineage} lineage with a code author; name an eligible reviewer`);
  }
  const panelKeys = [p.panel?.panelPrimary, ...(p.panel?.judges ?? [])].filter(Boolean);
  for (const key of [...new Set([isBaselineSwap(p) ? null : p.primary, ...(p.companions ?? []), ...panelKeys, ...(p.alternates ?? [])].filter(Boolean))]) {
    if (modeOf(ROUTES[key], p.maxRuntimeMode) === null) problems.push(`${key} needs ${ROUTES[key].minMode}, above the invoker's ${p.maxRuntimeMode}`);
  }
  if (skillOf(p) === "review-loop") {
    if (p.panel !== undefined) problems.push("panel is a hillclimb roster; review-loop has no panel phase");
    if (p.alternates !== undefined) problems.push("alternates are for a hillclimb roster; review-loop uses the standing routes");
    for (const key of [p.primary, ...(p.companions ?? [])].filter(Boolean)) {
      if (ROUTES[key].scoringOnly) problems.push(`${key} is a hillclimb scoring route, not a review-loop reviewer`);
    }
  } else {
    if (p.primary === undefined && p.namedReviewer === undefined) problems.push("hillclimb needs its confirmed primary (primary or namedReviewer)");
    if (p.panel === undefined) problems.push("hillclimb needs panel: the confirmed judges, or judges [] for a confirmed primary-only run");
    if (p.singleRound === true) problems.push("review_rounds: 1 does not apply to hillclimb scoring");
    const judges = p.panel?.judges ?? [];
    if (new Set(judges).size !== judges.length) problems.push("panel judges must be distinct");
    const leads = [p.primary, p.panel?.panelPrimary].filter(Boolean);
    if (judges.some((k) => leads.includes(k))) problems.push("a panel judge cannot also be the primary or panelPrimary");
    if (judges.length === 0 && p.panel?.panelPrimary !== undefined) problems.push("panelPrimary needs a panel");
    if (judges.length === 0 && p.panel?.trigger === "baseline") problems.push("a baseline panel trigger needs panel judges");
    const overlaps = rosterOverlaps(p, packetScorerGroups(p));
    if (overlaps.length > 0 && !String(p.overlapApproval ?? "").trim()) {
      problems.push(`lineage overlap needs the operator's recorded approval (overlapApproval): ${overlaps.join("; ")}`);
    }
  }
  const n = p.namedReviewer;
  if (n !== undefined) {
    if (p.primary !== undefined) problems.push("name either primary or namedReviewer, not both");
    if (skillOf(p) === "review-loop" && p.scope === "code" && p.codeAuthors.includes(n.lineage)) problems.push(`${n.label} shares the ${n.lineage} lineage with a code author`);
    if (/^(max|ultra|ultrathink)$/i.test(n.effort.value)) problems.push("namedReviewer effort is above the xhigh ceiling");
    if (!n.instanceId.trim() || !n.model.trim() || !n.label.trim()) problems.push("namedReviewer needs label, instanceId and model");
  }
  const lim = p.limits ?? {};
  if (lim.repairRounds !== undefined && !(Number.isInteger(lim.repairRounds) && lim.repairRounds >= 0)) problems.push("limits.repairRounds must be a whole number");
  if (lim.deadline !== undefined && !Number.isFinite(Date.parse(lim.deadline))) problems.push("limits.deadline must be an ISO 8601 time");
  const c = p.continuation;
  if (c !== undefined) {
    if (!c.priorRun.trim() || !c.approval.trim()) problems.push("continuation needs priorRun and the operator's approval");
    for (const field of ["approval", "change"]) {
      if (/^<.*>$/.test(String(c[field] ?? "").trim())) problems.push(`continuation.${field} still holds the continueWith placeholder; write the operator's words`);
    }
    if (!(Number.isInteger(c.repairsUsed) && c.repairsUsed >= 0)) problems.push("continuation.repairsUsed must be a whole number");
    const prior = c.priorLedger;
    if (prior === undefined) problems.push("continuation needs priorLedger: the prior run's final score ledger, so the chart keeps its history");
    else {
      if (prior.run.scale.min !== s.min || prior.run.scale.max !== s.max) {
        problems.push(`a continuation keeps the prior scale ${prior.run.scale.min} to ${prior.run.scale.max}; start a fresh run to change it`);
      }
      if (prior.eras.length === 0 || prior.rounds.length === 0) problems.push("continuation.priorLedger needs its eras and rounds");
      else problems.push(...priorLedgerProblems(prior));
    }
  }
  return problems;
}

// Review's selection rule: after the gates, the highest-scored provider wins; null is unknown
// and cannot win; with no scored candidate, keep the static order.
function selectPrimary(p, pace, available) {
  const gates = ["grok: no verified T3 route on this host (#325)"];
  const eligible = STATIC_ORDER.filter((key) => {
    const route = ROUTES[key];
    if (lineageBlocked(p, key)) gates.push(`${key}: ${route.lineage} wrote code`);
    else if (modeOf(route, p.maxRuntimeMode) === null) gates.push(`${key}: needs ${route.minMode}`);
    else if (!available.has(key)) gates.push(`${key}: not reported available`);
    else return true;
    return false;
  });
  if (eligible.length === 0) return { order: [], basis: "no eligible reviewer", gates };
  const scored = eligible
    .map((key) => ({ key, pace: pace?.providers?.find((x) => x.provider === ROUTES[key].instanceId) }))
    .filter((x) => typeof x.pace?.paceScore === "number");
  if (scored.length === 0) return { order: eligible, basis: "no eligible provider has a paceScore; static order, capacity unknown", gates };
  const byScore = [...scored].sort((a, b) => b.pace.paceScore - a.pace.paceScore || STATIC_ORDER.indexOf(a.key) - STATIC_ORDER.indexOf(b.key));
  const top = byScore[0];
  return { order: [...new Set([...byScore.map((x) => x.key), ...eligible])],
    basis: `${top.key}: ${top.pace.provider} paceScore ${top.pace.paceScore} (${top.pace.paceBasis ?? "basis not reported"}) at ${pace.observedAt}`, gates };
}

// A judge's own claim conflicts when it names another family and not its own, a sibling model,
// an effort other than its route's, or a version next to a family word other than its route's.
function identityConflict(key, claim) {
  const text = String(claim ?? "").toLowerCase();
  const route = ROUTES[key];
  const has = (w) => new RegExp(`(^|[^a-z])${w}([^a-z]|$)`).test(text);
  const conflicts = [];
  const others = Object.keys(FAMILY_WORDS).filter((f) => f !== route.lineage && FAMILY_WORDS[f].some(has));
  const own = FAMILY_WORDS[route.lineage] ?? [];
  if (others.length > 0 && !own.some(has)) conflicts.push(`names ${others.join(", ")}`);
  const siblings = (SIBLINGS[key] ?? []).filter(has);
  if (siblings.length > 0) conflicts.push(`names ${siblings.join(", ")}`);
  const efforts = EFFORT_WORDS.filter((w) => w !== route.effort.value && has(w));
  if (efforts.length > 0) conflicts.push(`reports effort ${efforts.join(", ")}`);
  const versions = own.length === 0 ? []
    : [...text.matchAll(new RegExp(`(?:${own.join("|")})[\\s-]*v?(\\d+(?:\\.\\d+)?)`, "g"))].map((m) => m[1]);
  if (versions.length > 0 && !versions.includes(route.version)) conflicts.push(`reports version ${versions.join(", ")}`);
  return conflicts.length > 0 ? conflicts : null;
}

function judgedProblems(p, key, candidate, v, scoring) {
  const problems = [];
  if (!sameRevision(v.revision, candidate)) problems.push(`reviewed revision ${v.revision} is not the frozen candidate ${candidate}`);
  if (scoring) {
    const s = p.scale;
    if (typeof v.score !== "number" || !Number.isFinite(v.score) || v.score < s.min || v.score > s.max) problems.push(`score must be a number from ${s.min} to ${s.max}`);
    const bullets = v.bullets.filter((b) => b.trim());
    if (bullets.length < 3 || bullets.length > 5) problems.push("rationale needs 3 to 5 bullets");
  }
  const conflict = identityConflict(key, v.model);
  if (conflict !== null) problems.push(`identity conflict: "${String(v.model).slice(0, 80)}" (${conflict.join("; ")}), not ${ROUTES[key].label}`);
  return problems;
}

// Keep only dimensions the score chart accepts.
function cleanDimensions(dimensions, scale) {
  return (dimensions ?? []).filter((d) => d.name.trim() && d.score >= scale.min && d.score <= scale.max
    && (d.weight === undefined || d.weight > 0)).map((d) => ({ ...d, name: d.name.trim() }));
}

function gatePasses(target, metric, checks, covered) {
  return metric !== null && metric >= target && checks.passed && checks.coverage && covered;
}

// Only a strict increase over the best resets the counter.
function progress(state, metric) {
  if (metric !== null && (state.best === null || metric > state.best.metric)) return { improved: true, counter: 0 };
  return { improved: false, counter: state.counter + 1 };
}

// The best candidate that keeps every required fix (seq at or after the floor); the earlier wins a tie.
function eligibleBest(scored, floor) {
  let best = null;
  for (const c of scored) {
    if (c.seq >= floor && c.metric !== null && (best === null || c.metric > best.metric)) best = c;
  }
  return best;
}

// The candidate an incomplete stop hands back: the current phase's best eligible scored candidate
// across eras when the contract never changed, else the current era's; in a panel phase with no
// complete panel score, the panel-entry candidate; else the required-fix candidate or the latest
// work, unscored.
function finalCandidate(eras, floor, latest, floorWork) {
  const last = eras[eras.length - 1];
  const comparable = eras.every((e) => e.comparable);
  const best = eligibleBest((comparable ? eras : [last]).flatMap((e) => e.scored).filter((c) => c.phase === last.phase), floor);
  if (best !== null) {
    return { candidate: best.candidate, metric: best.metric, entry: best,
      note: `${comparable ? "best fully scored candidate that keeps required fixes" : "best under the current contract; earlier scores historical"}`
        + `${last.phase === "panel" ? " (lowest panel score)" : ""}` };
  }
  const entry = last.phase === "panel" ? last.panelEntry : null;
  if (entry !== null && entry.seq >= floor) {
    return { candidate: entry.candidate, metric: null, entry: null, note: "the panel-entry candidate; it has no complete panel result" };
  }
  // The unscored fallback never drops below the required-fix floor.
  const work = latest.seq >= floor ? latest : floorWork;
  return { candidate: work.candidate, metric: null, entry: null, note: `no ranked best; latest eligible work from ${work.source}, unscored` };
}

// The run's score ledger. A continuation puts the prior run family's eras and rounds first, so one
// chart covers every run; the first era of this run is comparable to the prior one only when both
// carry the same era fingerprint: contract (decimal places included), starting phase and scoring roster.
function ledgerOf(p, runId, status, eras, rounds, reviewers) {
  const prior = p.continuation?.priorLedger;
  const k = prior?.eras.length ?? 0;
  const priorLast = prior ? prior.eras[k - 1] : null;
  // The prior era as it ended (phase and active scorers) against this era as it opens.
  const priorEnd = priorLast?.end_fingerprint ?? priorLast?.fingerprint;
  const continues = prior !== undefined && eras.length > 0 && priorEnd !== undefined && priorEnd === eras[0].print;
  const own = eras.map((e, i) => ({
    id: `e${i + 1 + k}`,
    label: i === 0 ? (p.continuation ? `Continuation of ${p.continuation.priorRun}` : "Original contract") : "Recovery era",
    target: e.target,
    ...(e.target !== p.target ? { original_target: p.target } : {}),
    historical: i < eras.length - 1 && !eras[i + 1].comparable,
    comparable_to_prev: i === 0 ? (prior ? continues : true) : e.comparable,
    ...(e.print ? { fingerprint: e.print, end_fingerprint: e.endPrint ?? e.print } : {}),
    ...(e.recovery ? { recovery: e.recovery }
      : i === 0 && p.continuation ? { recovery: { kind: "continuation", label: `Continuation of ${p.continuation.priorRun}`,
        trigger: `run ${p.continuation.priorRun} ended without meeting its target`, diagnosis: p.continuation.approval.trim() || "operator-approved continuation",
        fix: String(p.continuation.change ?? "").trim() || "the approved changed approach" } } : {}),
  }));
  const shift = (eid) => `e${Number(String(eid).slice(1)) + k}`;
  const ownRounds = (rounds.length ? rounds : [{ id: "B0", label: "Baseline", era: "e1", phase: "primary",
    expected_reviewers: [reviewers[0]?.id ?? "none"], status: "unscored", failure_note: "no evaluation completed", scores: [] }])
    .map((r) => (k ? { ...r, era: shift(r.era) } : r));
  const allReviewers = reviewers.length ? reviewers : [{ id: "none", label: "no judge" }];
  if (!prior) {
    return { version: 1, run: { title: p.title, id: runId, skill: skillOf(p), status, scale: { min: p.scale.min, max: p.scale.max, precision: decimalsOf(p.scale) } },
      reviewers: allReviewers, eras: own, rounds: ownRounds };
  }
  // Prior eras are renumbered ahead of this run's; prior round ids gain their run's prefix once.
  const idMap = new Map(prior.eras.map((e, i) => [String(e.id).trim(), `e${i + 1}`]));
  const priorEras = prior.eras.map((e, i) => ({ ...e, id: `e${i + 1}`, ...(i === k - 1 && !continues ? { historical: true } : {}) }));
  const priorRounds = prior.rounds.map((r) => ({ ...r, id: mergedRoundId(prior, r.id), era: idMap.get(String(r.era).trim()) ?? r.era }));
  const mergedReviewers = [...prior.reviewers.map((r) => ({ id: r.id, label: r.label, ...(r.role ? { role: r.role } : {}) }))];
  for (const r of allReviewers) if (!mergedReviewers.some((x) => x.id === r.id) && !(r.id === "none" && mergedReviewers.length)) mergedReviewers.push(r);
  return {
    version: 1,
    run: { title: p.title, id: runId, skill: skillOf(p), status,
      scale: { min: p.scale.min, max: p.scale.max, precision: Math.max(prior.run.scale.precision, decimalsOf(p.scale)) } },
    reviewers: mergedReviewers,
    eras: [...priorEras, ...own],
    rounds: [...priorRounds, ...ownRounds],
  };
}

function roundEntry(p, era, label, id, candidate, judges, failure, phase) {
  const scores = judges.filter((j) => j.scoring).map((j) => {
    const retry = j.retried ? { retried: true, retry_note: j.retryNote } : {};
    const dims = cleanDimensions(j.dimensions, p.scale);
    return typeof j.score === "number"
      ? { reviewer: j.key, score: quantise(j.score, p.scale), bullets: j.bullets.map((b) => b.trim()).filter(Boolean).slice(0, 5),
        ...(dims.length ? { dimensions: dims } : {}), ...retry }
      : { reviewer: j.key, score: null, status: j.status, failure_note: j.problems.join("; ") || j.status, ...retry };
  });
  const status = failure ? (scores.some((s) => s.score !== null) ? "incomplete" : "unscored")
    : scores.every((s) => s.score !== null) ? "scored" : "incomplete";
  return { id, label, candidate, era: `e${era}`, phase, expected_reviewers: judges.filter((j) => j.scoring).map((j) => j.key),
    status, ...(status === "scored" ? {} : { failure_note: failure ?? "the judge returned no score" }), scores };
}

function findingsText(judges, withEvidence) {
  const lines = [];
  for (const j of judges) {
    for (const r of j.rechecks ?? []) {
      lines.push(`- ${j.key}/${bareId(j.key, r.id)} recheck: ${r.status}. ${r.evidence.slice(0, 600)}`);
    }
    for (const f of j.findings ?? []) {
      lines.push(`- ${j.key}/${bareId(j.key, f.id)} ${f.severity} ${f.title} @ ${f.location}: ${f.impact}`
        + (withEvidence ? `\n  evidence: ${f.evidence.slice(0, 1500)}` : ""));
    }
    if (j.coverageComplete === false) lines.push(`- ${j.key} coverage gap: ${String(j.coverageGaps ?? "").slice(0, 600)}`);
  }
  return lines.length ? lines.join("\n") : "- none reported";
}

// A judge's own findings, unprefixed, for it to recheck on the next candidate.
function ownFindingsText(j) {
  return (j.findings ?? []).map((f) => `- ${bareId(j.key, f.id)} ${f.severity} ${f.title} @ ${f.location}: ${f.impact}`).join("\n");
}

function receiptsText(judges) {
  return judges.filter((j) => j.thread).map((j) => `- ${j.key}: thread ${j.thread}, turn ${j.executed?.turnId ?? "unknown"}, `
    + `requested ${ROUTES[j.key].model} ${ROUTES[j.key].effort.id}=${ROUTES[j.key].effort.value}, executedModel `
    + `${j.executed?.model ?? "null"} (${j.executed?.verified ? "verified" : "unverified"}), effort unverified (the host records none), `
    + `self-reported "${String(j.claim ?? "").slice(0, 80)}"`).join("\n") || "- none";
}

// ---------- workflow ----------

export default T3.workflow(
  "scored-loop",
  { version: 16, payload: T3.WebhookRequest, triggers: [T3.webhook("start")] },
  (input, { id }) =>
    Effect.gen(function* () {
      const parsed = yield* T3.step.try("packet", { returns: Packet }, Effect.try(() => decodePacket(JSON.parse(input.body))));
      if (parsed.outcome === "failed") {
        const thread = (() => {
          try {
            const t = JSON.parse(input.body).invokerThread;
            return typeof t === "string" && t.trim() ? t : null;
          } catch {
            return null;
          }
        })();
        if (thread !== null) {
          yield* T3.agent("callback", { thread: { threadId: thread }, brief: [`[T3 workflow scored-loop, run ${id}]`,
            "Packet rejected before any judge was dispatched. Nothing was scored.", `- ${parsed.reason.slice(0, 600)}`,
            "Fix the packet and start again with a new idempotency key."].join("\n") });
        }
        return yield* T3.stop(`packet rejected: ${parsed.reason}`);
      }
      const p = { ...parsed.value };
      const test = p.test !== undefined;
      const skill = skillOf(p);
      const climb = skill === "hillclimb";
      yield* T3.title(`${test ? "[test] " : ""}${skill}: ${p.title.slice(0, 80)}`);
      const head = `[T3 workflow scored-loop (${skill}), run ${id}]`;
      const tell = (name, lines) => T3.agent(name, { thread: { threadId: p.invokerThread }, brief: [head, ...lines].filter((l) => l !== "").join("\n") });
      const problems = packetProblems(p);
      if (problems.length > 0) {
        yield* tell("callback", ["Packet rejected; no judge was dispatched.", ...problems.map((x) => `- ${x}`),
          "Fix the packet and start again with a new idempotency key."]);
        return { run: id, outcome: "rejected", problems };
      }
      // The validated target, stored as the grid value it displays as.
      p.target = gridValue(p.scale, p.target);

      // ----- limits: one guard, journaled, before each dispatch and after each invoker result -----
      const deadline = p.limits?.deadline !== undefined ? Date.parse(p.limits.deadline) : NO_DEADLINE;
      const roundCap = p.limits?.repairRounds ?? null;
      const judgeMs = Math.round((p.judgeMinutes ?? 60) * 60000);
      const repairMs = Math.round((p.repairMinutes ?? 240) * 60000);
      // A user-named reviewer joins this run's routes under a run-scoped key.
      const baselineSwap = isBaselineSwap(p);
      const namedKey = p.namedReviewer ? `named-${String(id).slice(0, 8)}` : null;
      // OpenCode, Grok and Muse routes fall back to asking for approval below full access (t3-dispatch.md),
      // so a named reviewer on them needs full access or is skipped by the mode gate.
      if (namedKey !== null) {
        ROUTES[namedKey] = { ...p.namedReviewer, label: `${p.namedReviewer.label} (named)`,
          ...(["opencode", "grok", "muse"].includes(p.namedReviewer.instanceId) ? { minMode: "full-access" } : {}) };
      }
      if (namedKey !== null && !baselineSwap && modeOf(ROUTES[namedKey], p.maxRuntimeMode) === null) {
        yield* tell("callback", [`${p.namedReviewer.label} on ${p.namedReviewer.instanceId} needs full access, above the invoker's ${p.maxRuntimeMode}.`,
          "Ask the operator for an eligible alternative, then start again with a new idempotency key."]);
        return { run: id, outcome: "blocked", problems: ["named reviewer needs full access"] };
      }
      const runRoutes = ROUTE_KEYS.filter((k) => climb || !ROUTES[k].scoringOnly);
      const keys = namedKey === null ? runRoutes : [...runRoutes, namedKey];
      const routeList = keys.map((k) => `- ${k}: ${ROUTES[k].instanceId}/${ROUTES[k].model} with ${ROUTES[k].effort.id}=${ROUTES[k].effort.value}`);
      const reportAsk = [
        "Also call orchestrator_capabilities and report as availableRoutes each route key below whose provider lists",
        "its exact model with that effort option now (leave out any you could not confirm):",
        ...routeList,
        p.limits?.spendCap ? `Report spendCapReached true if this spend cap is reached: ${p.limits.spendCap}.` : "Report spendCapReached false.",
      ];
      // The latest invoker report. `available` is null when the last report failed: no judge dispatches then.
      let available = test ? new Set(keys) : null;
      let capReached = false;
      const report = (value) => {
        if (value === null) {
          if (!test) available = null;
          return;
        }
        // A caller cannot know the run-scoped key of a named reviewer before the run starts, so `named`
        // stands for it.
        available = new Set(value.availableRoutes.map((k) => (k === "named" && namedKey !== null ? namedKey : k)).filter((k) => keys.includes(k)));
        capReached = capReached || value.spendCapReached === true;
      };
      // The stop decision is journaled, so a replay repeats the decision the original run made and keeps
      // its recorded evidence. The dispatch timeout is measured live every time (`live`): a dispatch that
      // replays after the deadline gets no time and is interrupted at once, and a result observed after
      // the deadline is caught by the guard that follows it.
      const limits = (name, wanted) => Effect.gen(function* () {
        const g = yield* T3.step(name, { returns: Schema.Struct({ stop: Schema.NullOr(Schema.String) }) },
          Effect.sync(() => ({ stop: capReached ? "spend-cap" : deadline - Date.now() <= 0 ? "deadline" : null })));
        const live = deadline === NO_DEADLINE ? wanted : Math.max(1, Math.min(wanted, deadline - Date.now()));
        return { stop: g.stop, left: live };
      });
      const limitStop = (kind) => ({ stop: kind === "spend-cap" ? "spend cap reached" : "run deadline passed", limit: kind });
      const pauses = new Set(p.test?.pauseAt ?? []);
      const pausePoint = (name) => (pauses.has(name)
        ? Effect.gen(function* () {
          const armed = yield* T3.step(`test/${name}/armed`, { returns: Schema.Number }, Effect.sync(() => Date.now()));
          yield* T3.step(`test/${name}`, { returns: Schema.Number }, Effect.suspend(() => {
            const wait = armed + (p.test.pauseSeconds ?? 60) * 1000 - Date.now();
            return wait > 0 ? Effect.fail(new Error(`test pause at ${name}: resume after ${Math.ceil(wait / 1000)} more second(s)`)) : Effect.succeed(Date.now());
          }));
        })
        : Effect.void);

      // ----- selection -----
      // The packet's startReport replaces a separate selection turn.
      let pace = null;
      const selectionProblem = test ? "test run: static order" : null;
      if (!test) {
        pace = p.startReport;
        report(pace);
      }
      if (capReached) {
        yield* tell("callback", [`Spend cap reached before any judge was dispatched: ${p.limits?.spendCap ?? "as reported"}. Nothing was scored.`]);
        return { run: id, outcome: "blocked", problems: ["spend cap reached"] };
      }
      if (available === null) {
        yield* tell("callback", [`Route availability could not be established, so no judge was dispatched: ${selectionProblem}.`,
          "Start again with a new idempotency key and a fresh startReport."]);
        return { run: id, outcome: "blocked", problems: ["route availability unknown"] };
      }
      let selection;
      // Hillclimb's panel: the judges that join at the trigger, and the primary from then on.
      let panelJudges = [...(p.panel?.judges ?? [])];
      const panelLead = (p.panel?.judges ?? []).length > 0 ? p.panel?.panelPrimary ?? null : null;
      // A baseline panel with a panelPrimary swaps the original primary out before any score, so
      // panelPrimary leads from the start and the idle primary is neither checked nor authorised.
      let primary = baselineSwap ? panelLead : namedKey ?? p.primary ?? null;
      // Hillclimb's operator-authorised routes for the single automatic recovery (budget-exhaustion.md step 3).
      const authorised = [...new Set([primary, panelLead, ...panelJudges, ...(p.alternates ?? [])].filter(Boolean))];
      if (primary !== null) {
        const how = climb ? `confirmed by the operator: ${ROUTES[primary].label}`
          + `${panelJudges.length ? `; panel ${panelJudges.join(", ")} from ${p.panel.trigger === "baseline" ? "the baseline" : "the primary gate"}` : "; primary-only run"}`
          + `${panelLead ? `; panel primary ${panelLead}` : ""}${p.alternates?.length ? `; alternates ${p.alternates.join(", ")}` : ""}${p.overlapApproval ? `; approved overlap: ${p.overlapApproval}` : ""}`
          : `named by the user: ${ROUTES[primary].label}`;
        selection = { order: [primary], basis: how, gates: available.has(primary) ? [] : [`${primary}: not reported available`] };
        if (!available.has(primary)) primary = null;
      } else {
        selection = selectPrimary(p, pace, available);
        if (selectionProblem) selection.basis += ` (${selectionProblem})`;
        primary = selection.order[0] ?? null;
      }
      const offCompanions = (p.companions ?? []).filter((k) => !available.has(k));
      const offPanel = [panelLead, ...panelJudges].filter((k) => k !== null && !available.has(k));
      if (primary === null || offCompanions.length > 0 || offPanel.length > 0) {
        yield* tell("callback", [`No eligible, available reviewer for this roster: hold dependent ${climb ? "scoring" : "review"} for the operator's choice.`,
          ...selection.gates.map((g) => `- ${g}`), ...offCompanions.map((k) => `- companion ${k}: not reported available`),
          ...offPanel.map((k) => `- panel seat ${k}: not reported available`)]);
        return { run: id, outcome: "blocked", selection };
      }

      // ----- one evaluation: the primary and any companions on one frozen candidate -----
      const reviewers = [];
      const label = (key, role) => {
        if (!reviewers.some((r) => r.id === key)) reviewers.push({ id: key, label: ROUTES[key].label, role });
      };
      const priorFindings = {};
      let evalCount = 0;
      let synthetic = 0;
      const judgeOnce = (key, seat, candidate, contract, note) =>
        Effect.gen(function* () {
          const route = ROUTES[seat.key];
          const g = yield* limits(`${key}/limits`, judgeMs);
          if (g.stop !== null) return { ...seat, status: "limit", limit: g.stop, score: null, problems: [limitStop(g.stop).stop], thread: null };
          if (available === null || !available.has(seat.key)) {
            return { ...seat, status: "unavailable", score: null, problems: [`${seat.key} was not reported available by the latest invoker turn`], thread: null };
          }
          if (test) {
            const score = seat.scoring ? p.test.scores[seat.row] : null;
            if (seat.scoring && (score === null || score === undefined)) return { ...seat, status: "failed", score: null, problems: ["synthetic judge failure"], thread: null };
            const gap = (p.test.coverageGap ?? []).includes(evalCount);
            return { ...seat, status: seat.scoring ? "scored" : "reported", score, problems: [], thread: null, findings: [],
              bullets: [`synthetic score ${score} for ${candidate}`, "test run: no model judged this", "state-machine check only"],
              coverageComplete: !gap, coverageGaps: gap ? "synthetic coverage gap" : "none", claim: "synthetic" };
          }
          const ran = yield* T3.agent.try(key, {
            project: p.project,
            model: { instanceId: route.instanceId, model: route.model, options: [route.effort] },
            title: `${skill} ${seat.key}: ${p.title.slice(0, 50)}`,
            timeout: `${g.left} millis`,
            runtimeMode: modeOf(route, p.maxRuntimeMode),
            interactionMode: "default",
            returns: Judged,
            brief: [
              `${head} ${seat.scoring ? "Scoring" : "Companion"} review.`,
              `Read your role card first: ${CARD}`,
              seat.scoring ? "" : "You are a companion: report findings and evidence; set score to null.",
              "", `Task: ${p.title}`,
              `Checkout: ${p.checkout} (read it; do not edit, commit or switch branches there).`,
              `Frozen candidate: ${candidate}. Comparison base: ${p.base}.`,
              `Read it with: git -C ${p.checkout} diff ${p.base}..${candidate} and git -C ${p.checkout} show ${candidate}:<path>.`,
              "", "Acceptance criteria:", contract.criteria, "", "Rubric:", contract.rubric,
              contract.checks ? `Required checks under the current contract: ${contract.checks}` : "",
              `Scale ${p.scale.min} to ${p.scale.max}; scores round half up to ${decimalsOf(p.scale)} decimal place(s). Target ${fmt(contract.target, p.scale)}.`, "",
              "Permitted checks, scratch directory and evidence:", p.reviewContext, "",
              `Expected identity: ${route.label} (${route.instanceId}/${route.model}, ${route.effort.id}=${route.effort.value}), lineage ${route.lineage}.`,
              `Material ${climb ? "implementers'" : "code authors'"} lineages: ${p.codeAuthors.join(", ") || "none recorded"}.`,
              climb && p.overlapApproval ? `The operator approved this disclosed lineage overlap for scoring: ${p.overlapApproval}` : "",
              climb ? "Score independently: other judges' scores and verdicts are withheld from you." : "",
              note ? `Since the last evaluation: ${note}` : "",
              priorFindings[seat.key] && climb
                ? "First recheck each of your findings on the previous candidate against this candidate, and report each in rechecks\n"
                  + `as fixed or open, with evidence:\n${priorFindings[seat.key]}`
                : priorFindings[seat.key] ? `Your own findings on the previous candidate:\n${priorFindings[seat.key]}` : "",
              climb ? `Then list up to ${FINDINGS_CAP} findings: the issues that most affected your score, most important first. The score covers`
                + "\ncorrectness, accessibility and design alike. Report only real issues: fewer findings, or none, is a valid result;"
                + "\nnever pad the list. A finding still open keeps its id." : "",
              "", "Submit with t3_submit_output: revision (the SHA you reviewed), score (null for a companion), bullets (3 to 5,",
              "how the score was reached), optional dimensions, findings (stable id, SEV1-SEV3, title, location, evidence, impact),",
              climb ? "rechecks ({ id, status: fixed | open, evidence } for each earlier finding; [] when there were none)," : "",
              "coverageComplete (false if any required check, state or evidence could not be covered), coverageGaps, and model",
              "(your own model name, version and reasoning effort as you know them).",
            ].filter((l) => l !== "").join("\n"),
          });
          const thread = ran.thread?.threadId ?? null;
          if (ran.outcome !== "done") return { ...seat, status: "failed", score: null, problems: [ran.reason.slice(0, 300)], thread };
          const bad = judgedProblems(p, seat.key, candidate, ran.value, seat.scoring);
          // Hillclimb keeps the judge's first FINDINGS_CAP findings, which it ranked most important first.
          const findings = climb ? ran.value.findings.slice(0, FINDINGS_CAP) : ran.value.findings;
          const base = { ...seat, thread, findings, rechecks: ran.value.rechecks ?? [], claim: ran.value.model, coverageComplete: ran.value.coverageComplete,
            coverageGaps: ran.value.coverageGaps, bullets: ran.value.bullets.filter((b) => b.trim()), dimensions: ran.value.dimensions,
            ...(findings.length < ran.value.findings.length ? { trimmed: ran.value.findings.length - findings.length } : {}) };
          if (bad.length > 0) return { ...base, status: "invalid", score: null, problems: bad };
          return { ...base, status: seat.scoring ? "scored" : "reported", score: seat.scoring ? ran.value.score : null, problems: [] };
        });

      // Judges whose host receipt is still owed: they ran in a thread and no receipt was applied yet.
      const pendingOf = (judges) => judges.filter((j) => j.thread !== null && j.thread !== undefined && j.executed === undefined);
      const receiptAsk = (listed) => [
        "For each judge thread below, read it with t3_thread_read and report, for its run that submitted with t3_submit_output,",
        "the run ID as turnId, its executedModel, and the thread's run count as turns. Use null where the host shows nothing.",
        ...listed.map((j) => `- ${j.thread} (${j.key}, requested ${ROUTES[j.key].model})`),
      ];
      // Apply receipt rows to the listed judges; a recorded model other than the route's invalidates the judge.
      const applyReceipts = (judges, listed, rows, problem) => judges.map((j) => {
        if (!listed.includes(j)) return j;
        const r = rows.find((x) => x.thread === j.thread);
        const executed = { model: r?.executedModel ?? null, verified: Boolean(r?.executedModel), turns: r?.turns ?? null,
          turnId: r?.turnId ?? null, ...(problem ? { problem: problem.slice(0, 200) } : r ? {} : { problem: "no receipt returned for this thread" }) };
        if (executed.verified && !executedMatches(ROUTES[j.key], executed.model)) {
          return { ...j, executed, status: "invalid", score: null, problems: [...j.problems, `host executedModel ${executed.model} is not ${ROUTES[j.key].model}`] };
        }
        return { ...j, executed };
      });
      // Host receipts in a turn of their own, with a refreshed limits report.
      const withReceipts = (name, judges) =>
        Effect.gen(function* () {
          const listed = pendingOf(judges);
          if (listed.length === 0) return judges;
          const g = yield* limits(`${name}/limits`, 10 * 60000);
          const read = g.stop !== null ? { outcome: "failed", reason: limitStop(g.stop).stop } : yield* T3.agent.try(name, {
            thread: { threadId: p.invokerThread },
            timeout: `${g.left} millis`,
            returns: Receipts,
            brief: [`${head} Host receipts for judge threads. Do nothing else in this turn.`,
              ...receiptAsk(listed), ...reportAsk, "Submit with t3_submit_output."].join("\n"),
          });
          report(read.outcome === "done" ? read.value : null);
          return applyReceipts(judges, listed, read.outcome === "done" ? read.value.judges : [], read.outcome === "done" ? null : read.reason);
        });

      const history = [];
      // A full record of one judge attempt: receipt, self-report and every finding with its evidence.
      const snapshot = (j) => ({ key: j.key, status: j.status, score: j.score, thread: j.thread, executed: j.executed ?? null, claim: j.claim ?? null,
        problems: j.problems, coverageComplete: j.coverageComplete ?? null, coverageGaps: j.coverageGaps ?? null, findings: j.findings ?? [],
        rechecks: j.rechecks ?? [], ...(j.trimmed ? { trimmed: j.trimmed } : {}) });
      // Receipts that arrive after an attempt was recorded update that attempt's record.
      const refreshHistory = (ev) => {
        for (const entry of ev.hist ?? []) {
          entry.judges = entry.judges.map((s) => {
            const j = ev.judges.find((x) => x.thread && x.thread === s.thread);
            return j ? snapshot(j) : s;
          });
        }
      };

      // One evaluation of a frozen candidate, with one retry of failed judges on the same routes.
      // Limit stops are not retried. Every attempt, first tries included, enters the history.
      // Synthetic score rows are assigned in roster order before the concurrent dispatch, so they
      // never depend on which judge finishes first. Host receipts are owed afterwards: the next
      // repair turn carries them, or `settle` reads them before a decision that turn cannot carry.
      const row = (seat) => (test && seat.scoring ? { ...seat, row: synthetic++ } : seat);
      const summarise = (judges, ctx, limitStop0) => {
        const done = judges.every((j) => j.status === "scored" || j.status === "reported");
        // The metric is the primary's score alone, or the lowest score of a panel.
        const scores = judges.filter((j) => j.scoring).map((j) => j.score);
        return { ...ctx, judges, complete: done, covered: judges.every((j) => j.coverageComplete !== false),
          metric: done && scores.length > 0 && scores.every((s) => typeof s === "number") ? Math.min(...scores.map((s) => quantise(s, p.scale))) : null,
          limit: limitStop0 ?? judges.find((j) => j.status === "limit")?.limit ?? null };
      };
      const evaluate = (candidate, era, contract, note, rid, seats) =>
        Effect.gen(function* () {
          evalCount += 1;
          const tag = `e${era}/eval${evalCount}`;
          seats.forEach((s) => label(s.key, s.role));
          const first = seats.map(row);
          let judges = yield* Effect.all(first.map((seat, i) => judgeOnce(`${tag}/${i}`, seat, candidate, contract, note)), { concurrency: "unbounded" });
          const hist = [{ kind: "evaluation", round: rid, attempt: "first", era, candidate, judges: judges.map(snapshot) }];
          history.push(hist[0]);
          const failed = judges.filter((j) => j.status !== "scored" && j.status !== "reported" && j.status !== "limit");
          if (failed.length > 0) {
            const again = judges.map((j) => (failed.includes(j) ? row({ key: j.key, scoring: j.scoring, role: j.role }) : null));
            // A failed first attempt's receipt is never needed: its record keeps it unverified.
            const marked = judges.map((j) => (failed.includes(j) && j.thread ? { ...j, executed: { model: null, verified: false, turns: null, turnId: null, problem: "attempt failed; no receipt read" } } : j));
            judges = yield* Effect.all(marked.map((j, i) => (failed.includes(judges[i])
              ? judgeOnce(`${tag}/${i}/retry`, again[i], candidate, contract, note)
                .pipe(Effect.map((x) => ({ ...x, retried: true, retryNote: `first attempt: ${j.problems.join("; ")}` })))
              : Effect.succeed(j))), { concurrency: "unbounded" });
            hist.push({ kind: "evaluation", round: rid, attempt: "retry", era, candidate, judges: judges.map(snapshot) });
            history.push(hist[1]);
          }
          for (const j of judges) {
            if (j.findings !== undefined) priorFindings[j.key] = ownFindingsText(j);
          }
          const g = yield* limits(`${tag}/after`, 1);
          return summarise(judges, { tag, rid, candidate, era, contract, note, hist }, g.stop);
        });

      // Read owed receipts in their own turn. A judge a receipt invalidates gets its one retry if it
      // has not had one, and that retry's receipt is read at once; `recordOnly` records receipts and
      // dispatches nothing more, for a run that is ending anyway.
      const settle = (ev, recordOnly = false) =>
        Effect.gen(function* () {
          if (pendingOf(ev.judges).length === 0) return ev;
          let judges = yield* withReceipts(`${ev.tag}/receipts`, ev.judges);
          // The receipts turn reports the spend cap and may cross the deadline: check limits before deciding.
          const read = yield* limits(`${ev.tag}/receipts/after`, 1);
          const broken = judges.filter((j, i) => j.status === "invalid" && ev.judges[i].status !== "invalid");
          const settled = summarise(judges, ev, read.stop ?? ev.limit);
          refreshHistory(settled);
          if (broken.length === 0 || read.stop !== null || recordOnly) return settled;
          const again = judges.map((j) => (broken.includes(j) && !j.retried ? row({ key: j.key, scoring: j.scoring, role: j.role }) : null));
          judges = yield* Effect.all(judges.map((j, i) => (again[i] !== null
            ? judgeOnce(`${ev.tag}/${i}/receipt-retry`, again[i], ev.candidate, ev.contract, ev.note)
              .pipe(Effect.map((x) => ({ ...x, retried: true, retryNote: `first attempt: ${j.problems.join("; ")}` })))
            : Effect.succeed(j))), { concurrency: "unbounded" });
          judges = yield* withReceipts(`${ev.tag}/receipts/retry`, judges);
          const entry = { kind: "evaluation", round: ev.rid, attempt: "retry", era: ev.era, candidate: ev.candidate, judges: judges.map(snapshot) };
          history.push(entry);
          for (const j of judges) {
            if (j.findings !== undefined) priorFindings[j.key] = ownFindingsText(j);
          }
          const g = yield* limits(`${ev.tag}/settled`, 1);
          return summarise(judges, { ...ev, hist: [...ev.hist, entry] }, g.stop ?? ev.limit);
        });

      // ----- run state -----
      const eras = [];
      const rounds = [];
      let repairsUsed = p.continuation?.repairsUsed ?? 0;
      let seq = 0;
      let floor = 0;
      let latest = { candidate: p.candidate, checks: p.checks, seq: 0, source: "the baseline", requiredFix: false };
      // The candidate that set the required-fix floor: the oldest work any handback may return.
      let floorWork = latest;
      let lastEval = null;
      const repairsLeft = () => roundCap === null || repairsUsed < roundCap;
      const ledgerNow = (status) => ledgerOf(p, id, status, eras, rounds, reviewers);
      // Every committed candidate, scored or not, keeps the seq it first had; a required fix raises the floor at once.
      const seqs = new Map([[p.candidate, 0]]);
      const commit = (candidate, checks, source, requiredFix) => {
        if (!seqs.has(candidate)) {
          seq += 1;
          seqs.set(candidate, seq);
        }
        latest = { candidate, checks, seq: seqs.get(candidate), source, requiredFix };
        if (requiredFix && latest.seq >= floor) {
          floor = latest.seq;
          floorWork = latest;
        }
        return latest;
      };

      // Scores are reused across eras only for the same candidate under an identical contract, roster and
      // judge brief, so a setup-only recovery cannot re-judge an unchanged candidate to shop for a higher score.
      const scoreCache = new Map();
      // The seats of one evaluation: the primary alone, or with the whole panel, plus any companions.
      const seatsOf = (phase) => [
        { key: primary, scoring: true, role: phase === "panel" && panelLead !== null ? "Panel primary" : "Primary" },
        ...(phase === "panel" ? panelJudges.map((key) => ({ key, scoring: true, role: "Panel" })) : []),
        ...(p.companions ?? []).map((key) => ({ key, scoring: false, role: "Companion" })),
      ];
      // A seat's stable identity across runs: its exact route, never a run-scoped key such as a named reviewer's.
      const routeId = (key) => (key === null || key === undefined ? "none"
        : `${ROUTES[key].instanceId}/${ROUTES[key].model}/${ROUTES[key].effort.id}=${ROUTES[key].effort.value}`);
      // Fingerprints: the contract; an era (contract, starting phase and scoring roster), for charting a
      // continuation as comparable; and a whole evaluation (contract, base, phase and every seat), for reuse.
      const contractPrint = (contract) => hashText(JSON.stringify([JUDGE_BRIEF, skill, p.scope, p.scale.min, p.scale.max, decimalsOf(p.scale),
        contract.criteria, contract.rubric, contract.target, contract.checks, p.reviewContext]));
      // An era's phase and the routes that score in it: taken as an era opens and again whenever its phase changes.
      const phasePrint = (contract, phase) => hashText(JSON.stringify([contractPrint(contract), phase,
        seatsOf(phase).filter((s) => s.scoring).map((s) => routeId(s.key))]));
      // The comparison base is part of what a judge reads (base..candidate), so it is part of reuse.
      const evalPrint = (contract, phase) => hashText(JSON.stringify([contractPrint(contract), p.base, phase,
        seatsOf(phase).map((s) => `${routeId(s.key)}:${s.scoring ? "scores" : "reports"}`)]));
      const cacheKey = (contract, phase, candidate) => `${evalPrint(contract, phase)}:${candidate}`;

      const runEra = (index, start, contract, recoveryNote, startPhase) =>
        Effect.gen(function* () {
          const era = { target: contract.target, comparable: recoveryNote === null || recoveryNote.comparable, recovery: recoveryNote?.ledger,
            print: null, endPrint: null, best: null, counter: 0, scored: [], phase: "primary", panelEntry: null };
          eras.push(era);
          let at = start;
          let roundNo = 0;
          let note = recoveryNote ? `recovery fix: ${recoveryNote.fix}` : "";
          // Panel entry freezes the candidate and swaps in any preapproved panel primary.
          const enterPanel = () => {
            era.phase = "panel";
            era.panelEntry = at;
            // The panel best is seeded by the first complete panel evaluation, never by a primary score.
            era.best = null;
            if (panelLead !== null && !(startPhase === "panel" && recoveryNote?.primaryChanged)) primary = panelLead;
            era.endPrint = phasePrint(contract, era.phase);
          };
          if (startPhase === "panel") enterPanel();
          // The era as it opens: its phase and the routes scoring in it.
          era.print = phasePrint(contract, era.phase);
          era.endPrint = era.print;

          // Chart and rank one evaluation. With `prev`, replace that earlier record of the same evaluation
          // (receipts arrived and changed it) instead of adding one.
          const record = (ev, labelText, rid, phase, prev, voidNote) => {
            const cand = prev?.cand ?? { candidate: at.candidate, seq: at.seq, checks: at.checks };
            if (prev?.entry) {
              era.scored = era.scored.filter((c) => c !== prev.entry);
              if (scoreCache.get(prev.key) === prev.entry) scoreCache.delete(prev.key);
            }
            // A result excluded by a limit, an incomplete seat or a voided receipt is charted without a
            // score, so the chart never computes a gate the loop excluded.
            const excluded = ev.limit !== null ? `excluded: ${limitStop(ev.limit).stop}`
              : voidNote ?? (!ev.complete ? "evaluation incomplete after one retry" : null);
            const charted = excluded === null ? ev.judges : ev.judges.map((j) => (typeof j.score === "number"
              ? { ...j, score: null, status: "excluded", problems: [...j.problems, `scored ${j.score}, excluded: ${excluded}`] } : j));
            const roundIdx = prev ? prev.roundIdx : rounds.length;
            rounds[roundIdx] = roundEntry(p, index, labelText, rid, cand.candidate, charted, excluded, phase);
            lastEval = { candidate: cand.candidate, judges: ev.judges };
            const key = prev?.key ?? cacheKey(contract, phase, cand.candidate);
            let entry = null;
            if (excluded === null) {
              entry = { candidate: cand.candidate, metric: ev.metric, seq: cand.seq, checks: cand.checks, covered: ev.covered, judges: ev.judges, phase,
                print: prev?.entry?.print ?? evalPrint(contract, phase) };
              // A score with a coverage gap is not cached: a setup fix may obtain the missing evidence.
              if (ev.covered) scoreCache.set(key, entry);
              era.scored.push(entry);
            }
            return { ...ev, rec: { roundIdx, entry, key, labelText, rid, phase, cand } };
          };
          const judgeRound = (labelText, rid) =>
            Effect.gen(function* () {
              const phase = era.phase;
              const cached = scoreCache.get(cacheKey(contract, phase, at.candidate));
              if (cached !== undefined) {
                // An unchanged candidate under an unchanged contract and roster keeps its earlier score.
                rounds.push(roundEntry(p, index, `${labelText} (unchanged; earlier score reused)`, rid, at.candidate, cached.judges, null, phase));
                era.scored.push({ ...cached, seq: at.seq });
                return { judges: cached.judges, metric: cached.metric, complete: true, covered: cached.covered, limit: null,
                  tag: `${rid}/reused`, rid, candidate: at.candidate, era: index, contract, note, hist: [] };
              }
              // An approved continuation reuses a valid prior baseline score: the same candidate and evaluation
              // fingerprint (which names each seat's exact route, so a named reviewer matches across runs),
              // with complete coverage. The baseline carries one seat's result, so a roster with companions is
              // scored afresh, as is anything else.
              const prior = p.continuation?.baseline;
              if (index === 1 && rid === "E1B0" && phase === "primary" && prior !== undefined
                && seatsOf(phase).length === 1
                && prior.coverageComplete === true && sameRevision(prior.candidate, at.candidate) && prior.fingerprint === evalPrint(contract, phase)) {
                const g = yield* limits(`${rid}/reuse`, 1);
                // This run's reviewer id for the seat (a named reviewer's is run-scoped), so the chart knows it.
                label(primary, "Primary");
                const judges = [{ key: primary, scoring: true, role: "Primary", status: "scored", score: prior.score, bullets: prior.bullets,
                  problems: [], findings: prior.findings ?? [], thread: prior.judgeThread, coverageComplete: true, claim: `reused from run ${p.continuation.priorRun}`,
                  executed: { model: null, verified: false, turns: null, turnId: null, problem: `receipt read in run ${p.continuation.priorRun}` } }];
                rounds.push(roundEntry(p, index, `${labelText} (reused from run ${p.continuation.priorRun})`, rid, at.candidate, judges, null, phase));
                const entry = { candidate: at.candidate, metric: quantise(prior.score, p.scale), seq: at.seq, checks: at.checks, covered: true, judges, phase,
                  print: prior.fingerprint };
                era.scored.push(entry);
                // A resubmitted copy of this candidate keeps the reused score, as any scored candidate does.
                scoreCache.set(cacheKey(contract, phase, at.candidate), entry);
                for (const j of judges) priorFindings[j.key] = ownFindingsText(j);
                return { judges, metric: entry.metric, complete: true, covered: true, limit: g.stop,
                  tag: `${rid}/reused`, rid, candidate: at.candidate, era: index, contract, note, hist: [] };
              }
              const ev = yield* evaluate(at.candidate, index, contract, note, rid, seatsOf(phase));
              return record(ev, labelText, rid, phase, null, null);
            });
          // Read owed receipts now and re-record the evaluation when they change it.
          const settleRecord = (ev, recordOnly = false) =>
            Effect.gen(function* () {
              const s = yield* settle(ev, recordOnly);
              return s === ev || !s.rec ? s : record(s, s.rec.labelText, s.rec.rid, s.rec.phase, s.rec, null);
            });

          // Progress bookkeeping for the latest evaluation, undoable when its score is voided.
          let pre = { best: null, counter: 0 };
          let reviewed = null;
          let lastKind = "baseline";
          const apply = (e, kind) => {
            pre = { best: era.best, counter: era.counter };
            lastKind = kind;
            if (e.limit !== null || !e.complete) return;
            if (kind === "baseline") {
              era.best = { candidate: at.candidate, metric: e.metric };
              reviewed = { candidate: at.candidate, metric: e.metric, covered: e.covered };
            } else if (kind === "panel") {
              era.best = { candidate: at.candidate, metric: e.metric };
              era.counter = 0;
            } else if (!(gatePasses(contract.target, e.metric, at.checks, e.covered) && at.seq >= floor)) {
              // Gate before progress: a gate-passing candidate advances even on a tie.
              const step = progress(era, e.metric);
              era.counter = step.counter;
              if (step.improved) era.best = { candidate: at.candidate, metric: e.metric };
            }
          };
          const unapply = () => {
            era.best = pre.best;
            era.counter = pre.counter;
          };
          const actionOf = (e, kind) => {
            if (e.limit !== null) return { kind: "stop", out: limitStop(e.limit) };
            if (!e.complete) return { kind: "stop", out: { stop: kind === "panel" ? "panel evaluation failed after its one retry" : "evaluation failed after its one retry" } };
            if (gatePasses(contract.target, e.metric, at.checks, e.covered) && at.seq >= floor) return { kind: "gate" };
            if (era.counter >= 2) return { kind: "stop", out: { stop: "two consecutive rounds without a higher score" } };
            if (!repairsLeft()) return { kind: "stop", out: { stop: `repair-round limit of ${roundCap} reached`, limit: "rounds" } };
            // review_rounds: 1 allows one scored review (whichever era completes it) and one verified repair.
            if (p.singleRound === true && roundNo === 0 && !(reviewed?.covered ?? e.covered)) {
              return { kind: "stop", out: { stop: "single round: the review reported a coverage gap, so the one-round exception does not apply", single: "not-applicable" } };
            }
            return { kind: "repair" };
          };
          // Apply an evaluation and decide what follows. Only a repair turn can carry owed receipts, so
          // any other decision reads them first and decides again on the verified result.
          const conclude = (e0, kind) =>
            Effect.gen(function* () {
              let e = e0;
              apply(e, kind);
              let action = actionOf(e, kind);
              if (action.kind !== "repair" && pendingOf(e.judges).length > 0) {
                const s = yield* settleRecord(e);
                if (s !== e) {
                  unapply();
                  e = s;
                  apply(e, kind);
                  action = actionOf(e, kind);
                }
              }
              return { e, action };
            });

          const baseLabel = index === 1 ? (p.continuation ? "Continuation baseline" : "Baseline") : "Recovery baseline";
          let ev = yield* judgeRound(era.phase === "panel" ? `${baseLabel} (panel)` : baseLabel, `E${index}B0`);
          yield* pausePoint("after-baseline");
          let action;
          ({ e: ev, action } = yield* conclude(ev, "baseline"));

          for (;;) {
            if (action.kind === "stop") return action.out;
            if (action.kind === "gate") {
              if (era.phase === "primary" && panelJudges.length > 0) {
                // Panel entry (rounds.md): the whole confirmed panel scores this frozen candidate; the lowest
                // score seeds the panel best with a fresh counter. No repair round is consumed.
                enterPanel();
                const entryEval = yield* judgeRound("Panel entry", `E${index}P0`);
                ({ e: ev, action } = yield* conclude(entryEval, "panel"));
                continue;
              }
              era.accepted = { candidate: at.candidate, metric: ev.metric };
              return { accepted: { candidate: at.candidate, metric: ev.metric, checks: at.checks, judges: ev.judges } };
            }
            const single = p.singleRound === true && roundNo === 0;

            roundNo += 1;
            const rid = `E${index}R${roundNo}`;
            const base = eligibleBest(era.scored.filter((c) => c.phase === era.phase), floor)?.candidate ?? latest.candidate;
            const g = yield* limits(`${rid}/limits`, repairMs);
            if (g.stop !== null) return limitStop(g.stop);
            repairsUsed += 1;
            // Receipts owed for the judges of the evaluation this round repairs travel with the repair.
            const owed = pendingOf(ev.judges);
            let rep;
            if (test) {
              const n = repairsUsed;
              rep = { candidate: (p.test.resubmit ?? []).includes(n) ? base : `test-${index}-${roundNo}`,
                checks: { passed: !(p.test.failChecks ?? []).includes(n), coverage: true, summary: "synthetic" },
                buildable: !(p.test.unbuildable ?? []).includes(n), addsRequiredFix: (p.test.requiredFix ?? []).includes(n),
                summary: "synthetic repair", dispositions: [], stop: null, availableRoutes: keys,
                spendCapReached: p.test.capAfterRepair === n,
                verification: single ? { verified: !(p.test.failChecks ?? []).includes(n), summary: "synthetic verification" } : null };
            } else {
              const brief = (resume) => [
                `${head} Repair round ${roundNo} of era ${index}${climb ? `, ${era.phase} phase` : ""}.`,
                resume ? `This round's earlier turn was stopped before it submitted. If you already committed a repair from ${base} for this round,\n`
                  + "check it, finish it and submit that commit; otherwise repair as below. This resend uses no extra repair round." : "",
                era.phase === "panel" ? `Panel phase: the metric is the lowest score of ${seatsOf("panel").filter((s) => s.scoring).map((s) => s.key).join(", ")}.` : "",
                `Target ${fmt(contract.target, p.scale)}. Best ${fmt(era.best?.metric, p.scale)} on ${era.best?.candidate ?? "none"}. Latest ${fmt(ev.metric, p.scale)} on ${at.candidate}.`,
                `Scores round to ${decimalsOf(p.scale)} decimal place(s). Non-improving rounds: ${era.counter} of 2. Repairs used, this one included: ${repairsUsed}${roundCap === null ? "" : ` of ${roundCap}`}.`,
                deadline === NO_DEADLINE ? "" : `Run deadline: ${new Date(deadline).toISOString()}; this turn has ${Math.floor(g.left / 60000)} minute(s).`,
                "Findings from the latest evaluation:", findingsText(ev.judges, true), "",
                `Checks on ${at.candidate}: ${at.checks.passed ? "pass" : "fail"}, coverage ${at.checks.coverage ? "complete" : "incomplete"}: ${at.checks.summary}`,
                contract.checks ? `Required checks under the current contract (run these and name them in checks.summary): ${contract.checks}` : "",
                "", `Repair from ${base} under skills/${skill}/SKILL.md: decide each finding, fix the selected ones, keep every`,
                "earlier required fix, commit the result in the checkout and run the required checks on that commit.",
                single ? "review_rounds: 1 is adopted: repair only this round's findings, then verify every accepted repair as\nskills/review/references/single-round.md step 3 requires; there is no recheck. Report verification." : "",
                owed.length ? "\nAlso report host receipts in judges, for the judges that scored the candidate you are repairing. A receipt naming another\nmodel voids that round's score, never your repair." : "",
                ...(owed.length ? receiptAsk(owed) : []),
                "", "Update your score ledger with the score ledger below and render the score chart.",
                "Submit with t3_submit_output: candidate (the new commit SHA), checks, buildable, addsRequiredFix (true when later",
                "candidates must keep a fix this one adds), summary, dispositions for each finding with a note,",
                `verification (${single ? "{ verified, summary }" : "null"}), stop (null, or { reason, limit: none | spend-cap | deadline })${owed.length ? ", judges (the receipts)" : ""}.`,
                ...reportAsk,
                "You may finish in a later turn of this thread; submit once, when the repair is committed.",
                "", "Score ledger so far:", JSON.stringify(ledgerNow("in-progress")),
              ].filter((l) => l !== "").join("\n");
              const ask = (key, left, resume) => T3.agent.try(key, {
                thread: { threadId: p.invokerThread }, timeout: `${left} millis`, quiet: "30 minutes", returns: Repair, brief: brief(resume) });
              let ran = yield* ask(`${rid}/repair`, g.left, false);
              let resent = false;
              if (ran.outcome !== "done" && CANCELLED.test(ran.reason)) {
                resent = true;
                // The operator stopped the turn (often to answer something else): send it once more, no new round.
                history.push({ kind: "repair", round: rid, era: index, base, candidate: null, paused: ran.reason.slice(0, 300) });
                const again = yield* limits(`${rid}/resume/limits`, repairMs);
                if (again.stop !== null) return limitStop(again.stop);
                ran = yield* ask(`${rid}/repair/resume`, again.left, true);
              }
              if (ran.outcome !== "done") {
                report(null);
                history.push({ kind: "repair", round: rid, era: index, base, candidate: null, failed: ran.reason.slice(0, 600) });
                // The operator stopped this round twice: that is a decision, not a failure to recover from, so
                // the owed receipts are recorded and no judge is retried.
                const operatorStop = resent && CANCELLED.test(ran.reason);
                // The owed receipts still go on record before the stop, and a changed result redoes its progress.
                const s = yield* settleRecord(ev, operatorStop);
                if (s !== ev) {
                  unapply();
                  ev = s;
                  apply(ev, lastKind);
                }
                const failure = `repair step failed: ${ran.reason.slice(0, 300)}`;
                // A limit reached while the receipts were read is named, and it blocks the recovery.
                if (ev.limit !== null) return { ...limitStop(ev.limit), stop: `${failure}; then ${limitStop(ev.limit).stop}` };
                if (operatorStop) return { stop: `${failure} (stopped by the operator twice)`, operatorStop: true };
                return { stop: failure };
              }
              rep = ran.value;
              if (owed.length > 0) {
                const judges = applyReceipts(ev.judges, owed, rep.judges ?? [], null);
                const voided = judges.some((j, i) => j.status === "invalid" && ev.judges[i].status !== "invalid");
                const checked = summarise(judges, ev, ev.limit);
                refreshHistory(checked);
                if (voided) {
                  // The score never counted: undo its progress and chart the round unscored. The repair stands.
                  unapply();
                  if (reviewed !== null && reviewed.candidate === checked.candidate) reviewed = { ...reviewed, metric: null };
                }
                ev = checked.rec ? record(checked, checked.rec.labelText, checked.rec.rid, checked.rec.phase, checked.rec,
                  voided ? "score voided: a host receipt named another model" : null) : checked;
              }
            }
            report(rep);
            const now = commit(rep.candidate, rep.checks, `repair ${rid}${rep.stop ? " (stopped)" : ""}`, rep.addsRequiredFix);
            history.push({ kind: "repair", round: rid, era: index, base, candidate: rep.candidate, checks: rep.checks, buildable: rep.buildable,
              addsRequiredFix: rep.addsRequiredFix, summary: rep.summary, dispositions: rep.dispositions, stop: rep.stop, verification: rep.verification });
            if (rep.stop !== null) return { stop: `repair stopped: ${rep.stop.reason}`, ...(rep.stop.limit === "none" ? {} : { limit: rep.stop.limit }) };
            const after = yield* limits(`${rid}/after`, 1);
            if (after.stop !== null) return limitStop(after.stop);
            if (single) {
              // A voided review leaves no independent score, so the one-round exception cannot pass.
              const voidedReview = reviewed === null || reviewed.metric === null;
              const verified = !voidedReview && rep.verification?.verified === true && rep.checks.passed && rep.checks.coverage && rep.buildable;
              return { single: verified ? "verified" : "unverified", reviewed, repaired: now,
                verification: voidedReview ? "the review's score was voided by a host receipt naming another model; the repair stands unreviewed"
                  : rep.verification?.summary ?? "no verification reported" };
            }
            at = now;
            note = `${rep.summary} Dispositions: ${rep.dispositions.map((d) => `${d.id} ${d.disposition}`).join(", ") || "none"}.`;
            if (!rep.buildable) {
              // Unavailable score, one non-improvement increment; no fictional zero.
              era.counter += 1;
              rounds.push({ id: rid, label: `Round ${roundNo}`, candidate: at.candidate, era: `e${index}`, phase: era.phase,
                expected_reviewers: seatsOf(era.phase).filter((s) => s.scoring).map((s) => s.key), status: "unscored", failure_note: `candidate could not build or run: ${rep.summary}`, scores: [] });
              ev = { judges: [], metric: null, complete: true, covered: false, limit: null, hist: [] };
              action = actionOf(ev, "round");
              continue;
            }
            // A resubmitted candidate keeps its earlier score (judgeRound reuses it): never re-score to shop.
            const roundEval = yield* judgeRound(`Round ${roundNo}`, rid);
            ({ e: ev, action } = yield* conclude(roundEval, "round"));
          }
        });

      const contract0 = { criteria: p.criteria, rubric: p.rubric, target: p.target, checks: null };
      let outcome = yield* runEra(1, latest, contract0, null, climb && panelJudges.length > 0 && p.panel.trigger === "baseline" ? "panel" : "primary");
      let accepted = outcome.accepted ?? null;
      let stopReason = accepted ? null : outcome.stop ?? null;
      let recovery = null;
      let single = null;

      if (outcome.single !== undefined) {
        // review_rounds: 1 replaces the recheck and the score gate; no automatic recovery and no second scored round.
        single = outcome;
        stopReason = outcome.single === "verified" ? null : outcome.stop ?? `single-round verification incomplete: ${outcome.verification}`;
        recovery = { outcome: "not applicable", trigger: "review_rounds: 1", diagnosis: "the adopted one-round exception replaces rechecks", fix: "none", revised: null };
      } else if (accepted === null && outcome.operatorStop === true) {
        // Two operator stops of the same repair turn end the run; no automatic recovery overrides them.
        recovery = { outcome: "not applicable", trigger: stopReason, diagnosis: "the operator stopped the repair turn twice", fix: "none", revised: null };
      } else if (accepted === null && p.continuation !== undefined) {
        recovery = { outcome: "spent", trigger: stopReason, diagnosis: `spent by prior run ${p.continuation.priorRun}`, fix: "none", revised: null };
      } else if (accepted === null && p.singleRound === true && eras.some((e) => e.scored.length > 0)) {
        // The one permitted scored round completed: a recovery would need a second, so none runs.
        recovery = { outcome: "not applicable", trigger: stopReason, diagnosis: "review_rounds: 1 permits no second scored round", fix: "none", revised: null };
      } else if (accepted === null) {
        // ----- the single automatic recovery -----
        yield* pausePoint("before-recovery");
        const committed = yield* T3.step("recovery/committed", { returns: Schema.Struct({ trigger: Schema.String, at: Schema.Number }) },
          Effect.sync(() => ({ trigger: stopReason, at: Date.now() })));
        const capSpent = !repairsLeft();
        const from = latest;
        const failed = (diagnosis) => ({ outcome: "fix-failed", diagnosis, fix: "none", candidate: from.candidate, checks: from.checks,
          buildable: true, addsRequiredFix: false, revised: null, availableRoutes: [], spendCapReached: false });
        const g = yield* limits("recovery/limits", repairMs);
        let fix;
        let reported = false;
        if (outcome.limit === "deadline" || outcome.limit === "spend-cap" || g.stop !== null) {
          // An exhausted deadline or spend cap blocks every recovery action, setup included.
          fix = failed(`${limitStop(g.stop ?? outcome.limit).stop}: it blocks every recovery action`);
        } else if (test && p.test.recovery !== undefined) {
          const t = p.test.recovery;
          fix = { outcome: t.outcome, diagnosis: "synthetic", fix: "synthetic recovery", candidate: t.changes === false ? from.candidate : "test-recovery",
            checks: { passed: true, coverage: true, summary: "synthetic" }, buildable: true, addsRequiredFix: false, availableRoutes: keys, spendCapReached: false,
            revised: t.target === undefined ? null : { reason: "synthetic target revision", target: t.target } };
          reported = true;
        } else {
          // The diagnosis is journaled before any fix, so a lost fixing turn still leaves it on record
          // with the frozen candidate the recovery starts from (budget-exhaustion.md, step 1 `committed`).
          const diag = yield* T3.agent.try("recovery/diagnose", {
            thread: { threadId: p.invokerThread },
            timeout: `${g.left} millis`,
            returns: Schema.Struct({ diagnosis: Schema.String, plan: Schema.String }),
            brief: [`${head} Recovery, step 1 of 2: diagnose only. Change nothing in this turn.`,
              `The loop stopped incomplete: ${stopReason}. The recovery starts from ${from.candidate} (from ${from.source}).`,
              "Diagnose from the retained evidence (start no evaluator) and state the fix you will make. Submit diagnosis and plan.",
              "Findings from the latest evaluation:", findingsText(lastEval?.judges ?? [], true)].join("\n"),
          });
          history.push({ kind: "recovery", round: "recovery/diagnose", candidate: from.candidate, outcome: diag.outcome === "done" ? "diagnosed" : "diagnosis failed",
            checks: from.checks, buildable: true, addsRequiredFix: false, diagnosis: diag.outcome === "done" ? diag.value.diagnosis : diag.reason.slice(0, 600),
            fix: diag.outcome === "done" ? `planned: ${diag.value.plan}` : "none", revised: null });
        }
        if (fix === undefined) {
          const recorded = history[history.length - 1];
          const ran = recorded.outcome !== "diagnosed" ? { outcome: "failed", reason: `the diagnosis step failed: ${recorded.diagnosis}` } : yield* T3.agent.try("recovery/fix", {
            thread: { threadId: p.invokerThread },
            timeout: `${g.left} millis`,
            quiet: "30 minutes",
            returns: Fix,
            brief: [
              `${head} Recovery, step 2 of 2. The loop stopped incomplete: ${stopReason}.`,
              "This is the run's single automatic recovery; it has one step key and runs at most once.",
              `Recorded diagnosis: ${recorded.diagnosis}`, `Recorded plan: ${recorded.fix}`,
              "Follow skills/review/references/budget-exhaustion.md, 'One automatic recovery', steps 3 and 4: fix the diagnosed",
              "cause and freeze the result.",
              `Start from the latest committed candidate ${from.candidate} (from ${from.source}); keep every required fix.`,
              capSpent ? `The repair-round limit (${roundCap}) is spent: only a setup-only fix that leaves the candidate unchanged may recover.`
                : "A fix that changes the candidate consumes one repair round, whatever its outcome.",
              deadline === NO_DEADLINE ? "" : `Run deadline: ${new Date(deadline).toISOString()}; this turn has ${Math.floor(g.left / 60000)} minute(s).`,
              climb ? `The run stopped in the ${eras[0].phase} phase; the recovery keeps that phase and every confirmed scorer.` : "",
              "Permitted changes: repair strategy, implementation, setup, rubric, target (inside the scale), required checks (in",
              climb
                ? `revised.checks), and a roster seat replaced from this run's authorised routes (${authorised.join(", ")}) that is available and needs no new\n`
                  + "lineage approval: revised.primary for the current primary, revised.panel for the whole new panel list."
                : `revised.checks), and the primary reviewer from the standing routes (${STATIC_ORDER.join(", ")}) that are lineage-eligible\nand available.`,
              "A new provider or model, a user constraint, a repository gate, a permission, publication or scope change",
              "blocks it: return fix-failed.",
              "Findings from the latest evaluation:", findingsText(lastEval?.judges ?? [], true), "",
              "Submit with t3_submit_output: outcome (fixed or fix-failed), diagnosis, fix, candidate (the frozen commit to re-baseline),",
              "checks, buildable, addsRequiredFix (true when later candidates must keep a fix the recovery adds), and revised (null,",
              `or the changed target, rubric, criteria, checks${climb ? ", primary or panel" : " or primary"} with the reason).`,
              ...reportAsk,
              "You may finish in a later turn of this thread; submit once.",
              "", "Score ledger so far:", JSON.stringify(ledgerNow("in-progress")),
            ].filter((l) => l !== "").join("\n"),
          });
          fix = ran.outcome === "done" ? ran.value : failed(`the recovery step failed: ${ran.reason.slice(0, 300)}`);
          reported = ran.outcome === "done";
        }
        report(reported ? fix : null);
        fix = { ...fix, diagnosis: fix.diagnosis.trim() || "(not stated)", fix: fix.fix.trim() || "(not stated)" };
        const changes = fix.candidate !== from.candidate;
        if (changes && !capSpent) repairsUsed += 1;
        const after = yield* limits("recovery/after", 1);
        const rv = fix.revised;
        const next = rv?.primary ?? primary;
        const nextPanel = rv?.panel ?? panelJudges;
        // A replacement may not add a lineage overlap the operator has not already approved.
        const scorerOf = (k) => ({ name: k, lineage: ROUTES[k].lineage });
        const nextLead = eras[0].phase === "panel" ? null : panelLead;
        const groups2 = scorerGroups(scorerOf(next), nextLead !== null ? scorerOf(nextLead) : null, nextPanel.map(scorerOf));
        const before = overlapKinds(p, packetScorerGroups(p));
        const fresh = climb && (rv?.primary !== undefined || rv?.panel !== undefined)
          ? [...overlapKinds(p, groups2)].filter((x) => !before.has(x)) : [];
        const seatProblem = (k) => !(climb ? authorised : STATIC_ORDER).includes(k) || lineageBlocked(p, k) || modeOf(ROUTES[k], p.maxRuntimeMode) === null || (!climb && ROUTES[k].scoringOnly);
        const leads2 = [next, nextLead].filter(Boolean);
        const blocked = fix.outcome !== "fixed" ? null
          : after.stop !== null ? limitStop(after.stop).stop
          : !fix.buildable ? "the fixing turn marked its candidate unbuildable"
          : changes && capSpent ? "a candidate-changing fix is blocked: the repair-round limit is spent"
          : rv?.target !== undefined && !targetFits(p.scale, rv.target) ? `revised target ${rv.target} is outside the scale`
          : rv?.primary !== undefined && seatProblem(rv.primary) ? `${rv.primary} is not an eligible primary`
          : rv?.primary !== undefined && nextLead === null && nextPanel.includes(next) ? `${next} is already a panel judge`
          : rv?.panel !== undefined && !climb ? "review-loop has no panel to revise"
          : rv?.panel !== undefined && (panelJudges.length === 0 || rv.panel.length === 0) ? "a replacement cannot add or remove the panel phase"
          : rv?.panel !== undefined && (new Set(rv.panel).size !== rv.panel.length || rv.panel.some((k) => leads2.includes(k)) || rv.panel.some(seatProblem)) ? "the revised panel is not an eligible, distinct roster"
          : fresh.length > 0 ? `the replacement needs new lineage approval: ${fresh.join("; ")}`
          : available === null || !available.has(next) ? `${next} is not reported available now`
          : nextPanel.some((k) => available === null || !available.has(k)) ? "a panel judge is not reported available now"
          : (p.companions ?? []).some((k) => available === null || !available.has(k)) ? "a companion is not reported available now"
          : null;
        if (blocked !== null) fix = { ...fix, outcome: "fix-failed", diagnosis: `${fix.diagnosis} (${blocked})` };
        // Only an accepted fix becomes eligible work; a blocked fix's commit is reported, never handed back.
        const fixed = fix.outcome === "fixed" ? commit(fix.candidate, fix.checks, "the recovery", fix.addsRequiredFix) : null;
        history.push({ kind: "recovery", round: "recovery", candidate: fix.candidate, outcome: fix.outcome, checks: fix.checks,
          buildable: fix.buildable, addsRequiredFix: fix.addsRequiredFix, diagnosis: fix.diagnosis, fix: fix.fix, revised: rv });
        recovery = { trigger: stopReason, at: committed.at, outcome: fix.outcome, diagnosis: fix.diagnosis, fix: fix.fix, revised: rv,
          candidate: fix.candidate, eligible: fixed !== null };
        yield* pausePoint("after-recovery");
        if (fix.outcome === "fixed") {
          if (rv?.primary !== undefined) primary = rv.primary;
          if (rv?.panel !== undefined) panelJudges = [...rv.panel];
          const contract = { criteria: rv?.criteria ?? contract0.criteria, rubric: rv?.rubric ?? contract0.rubric,
            target: rv?.target !== undefined ? gridValue(p.scale, rv.target) : contract0.target, checks: rv?.checks ?? contract0.checks };
          const comparable = rv === null || Object.keys(rv).every((k) => k === "reason");
          // The recovery keeps the phase it stopped in (budget-exhaustion.md step 5).
          outcome = yield* runEra(2, fixed, contract, {
            comparable,
            primaryChanged: rv?.primary !== undefined,
            fix: `${fix.fix}${rv?.checks ? ` Required checks now: ${rv.checks}` : ""}`,
            ledger: { kind: "automatic", label: `Recovery${rv?.target !== undefined ? ` · ${p.target} → ${rv.target}` : ""}`,
              trigger: stopReason, diagnosis: fix.diagnosis, fix: fix.fix },
          }, eras[0].phase);
          accepted = outcome.accepted ?? null;
          stopReason = accepted ? null : `${stopReason}; after the recovery: ${outcome.stop}`;
        }
      }

      // ----- hand back -----
      const revisedPass = accepted !== null && eras.length > 1 && !eras[1].comparable;
      const status = accepted !== null ? (revisedPass ? "passed-revised" : "passed") : single?.single === "verified" ? "passed" : "goal-not-met";
      const final = accepted !== null
        ? { candidate: accepted.candidate, metric: accepted.metric, note: "accepted candidate", entry: { judges: accepted.judges, checks: accepted.checks } }
        : single?.single === "verified" || single?.single === "unverified"
          ? { candidate: single.repaired.candidate, metric: null,
            entry: { judges: eras.flatMap((e) => e.scored).find((c) => c.candidate === single.reviewed.candidate)?.judges ?? [], checks: single.repaired.checks },
            note: `${single.single === "verified" ? "fixes coordinator-verified, not independently re-reviewed" : "repairs not verified"}; `
              + `the score ${single.reviewed.metric} stays bound to the reviewed candidate ${single.reviewed.candidate}` }
          : finalCandidate(eras, floor, latest, floorWork);
      const finalJudges = final.entry?.judges ?? [];
      const ledger = ledgerNow(status);
      // The next continuation's packet fields, prefilled: the operator's approval and the changed approach
      // stay to be written. A continuation starts from the latest candidate (budget-exhaustion.md), so the
      // baseline is offered only for a complete, primary-only score of that candidate; the next run reuses
      // it only if its evaluation fingerprint still matches.
      const startEntry = eras.flatMap((e) => e.scored).filter((c) => c.candidate === latest.candidate && c.phase === "primary" && c.covered).pop();
      const startPrimary = startEntry?.judges.find((j) => j.scoring && typeof j.score === "number" && j.status === "scored");
      const continueWith = status === "passed" || status === "passed-revised" ? null : {
        priorRun: id, repairsUsed, approval: "<the operator's approval of the changed approach>", change: "<the changed approach>",
        priorLedger: ledger,
        ...(startEntry && startPrimary && startEntry.judges.length === 1 ? { baseline: {
          primary: startPrimary.key, score: startPrimary.score, bullets: startPrimary.bullets ?? [], judgeThread: startPrimary.thread ?? "none",
          candidate: startEntry.candidate, fingerprint: startEntry.print, coverageComplete: true, findings: startPrimary.findings ?? [] } } : {}),
      };
      const result = {
        run: id, test, status, final: { candidate: final.candidate, metric: final.metric, note: final.note, checks: final.entry?.checks ?? null },
        stopReason, recovery, repairsUsed, latest, requiredFixFloor: floor, single: single ? { outcome: single.single, verification: single.verification ?? null } : null,
        eras: eras.map((e, i) => ({ era: i + 1, target: e.target, comparable: e.comparable, phase: e.phase, panelEntry: e.panelEntry?.candidate ?? null,
          best: e.best, nonImprovingRounds: e.counter, fingerprint: e.print })),
        roster: { primary, panel: panelJudges, overlapApproval: p.overlapApproval ?? null },
        continuation: p.continuation ? { ...p.continuation, priorLedger: p.continuation.priorLedger ? "(merged into ledger)" : undefined } : null,
        selection, history, ledger, continueWith,
      };
      const latestScore = eras.flatMap((e) => e.scored).filter((c) => c.candidate === latest.candidate).pop();
      yield* tell("callback", [
        test ? "TEST RUN with synthetic scores. Report this result only." : "",
        `Result: ${status}${!revisedPass ? "" : eras[1].target !== p.target
          ? ` (revised target ${eras[1].target}; the original target ${p.target} was not met)`
          : ` (under a revised contract: ${JSON.stringify(recovery?.revised ?? {})}; the original contract's target ${p.target} was not met)`}`,
        `Final candidate: ${final.candidate} (${typeof final.metric === "number" ? fmt(final.metric, p.scale) : "no score"}; ${final.note})`,
        final.entry?.checks ? `Checks on the final candidate: ${final.entry.checks.passed ? "pass" : "fail"}, coverage ${final.entry.checks.coverage ? "complete" : "incomplete"}: ${final.entry.checks.summary}` : "",
        latest.candidate !== final.candidate
          ? `Latest eligible candidate: ${latest.candidate} from ${latest.source}${latest.requiredFix ? ", adds a required fix" : ""}; checks ${latest.checks?.passed ? "pass" : "fail or not run"}: `
            + `${latest.checks?.summary ?? "none"}; ${latestScore ? `scored ${fmt(latestScore.metric, p.scale)}` : "no complete score"}.`
          : "",
        recovery && recovery.eligible === false && recovery.candidate !== latest.candidate ? `The recovery's commit ${recovery.candidate} was blocked and is not eligible work.` : "",
        `Eras: ${eras.map((e, i) => `${i + 1}: target ${e.target}${climb ? `, ${e.phase} phase${e.panelEntry ? ` (panel entry ${e.panelEntry.candidate})` : ""}` : ""}, `
          + `best ${fmt(e.best?.metric, p.scale)}${e.accepted ? `, accepted ${fmt(e.accepted.metric, p.scale)} on ${e.accepted.candidate}` : ""}, non-improving rounds ${e.counter}`).join("; ")}.`,
        climb ? `Roster: primary ${primary}${panelJudges.length ? `; panel ${panelJudges.join(", ")}` : "; primary-only (confirmed)"}${p.overlapApproval ? `; approved overlap: ${p.overlapApproval}` : ""}.` : "",
        stopReason ? `Stop: ${stopReason}` : "",
        recovery ? `Recovery: ${recovery.outcome} after "${recovery.trigger}" — ${recovery.diagnosis}${recovery.revised ? ` Revised: ${JSON.stringify(recovery.revised)}` : ""}` : "Recovery: not used",
        `Reviewer selection: ${selection.basis}${selection.gates.length ? `; gates: ${selection.gates.join("; ")}` : ""}`,
        `Repairs used: ${repairsUsed}${roundCap === null ? "" : ` of ${roundCap}`}${p.continuation ? ` (including ${p.continuation.repairsUsed} from run ${p.continuation.priorRun})` : ""}.`,
        /deadline|spend cap/.test(stopReason ?? "") ? "An explicit limit is exhausted: do no further work under it." : "",
        `Findings on the final candidate ${final.candidate}:`, finalJudges.length ? findingsText(finalJudges, true) : "- no complete evaluation of this candidate",
        "Judge receipts for the final candidate:", receiptsText(finalJudges),
        "Attempt history (every evaluation attempt, repair and recovery, in order; the full records are in the run result):",
        ...history.map((h) => (h.kind === "evaluation"
          ? `- ${h.round} ${h.attempt} evaluation of ${h.candidate}:\n` + h.judges.map((j) => `  ${j.key} ${j.status}${typeof j.score === "number" ? ` ${j.score}` : ""}; `
            + `thread ${j.thread ?? "none"}, turn ${j.executed?.turnId ?? "unknown"}, executedModel ${j.executed?.model ?? "unverified"}, runs ${j.executed?.turns ?? "unknown"}, `
            + `self-report "${String(j.claim ?? "").slice(0, 80)}"${j.problems.length ? `; problems: ${j.problems.join("; ")}` : ""}`
            + `${j.coverageComplete === false ? `; coverage gap: ${j.coverageGaps}` : ""}\n`
            + (j.rechecks ?? []).map((r) => `    recheck ${bareId(j.key, r.id)} ${r.status}: ${r.evidence}\n`).join("")
            + (j.findings.map((f) => `    ${bareId(j.key, f.id)} ${f.severity} ${f.title} @ ${f.location}: ${f.impact} Evidence: ${f.evidence}`).join("\n") || "    no findings")
            + (j.trimmed ? `\n    (${j.trimmed} lower-ranked finding(s) beyond the cap of ${FINDINGS_CAP} were dropped)` : "")).join("\n")
          : h.kind === "recovery"
            ? `- recovery ${h.outcome} with ${h.candidate}: ${h.diagnosis}; fix: ${h.fix}; checks ${h.checks.passed ? "pass" : "fail"}${h.addsRequiredFix ? "; adds a required fix" : ""}`
            : h.paused
              ? `- ${h.round} repair turn stopped by the operator (${h.paused}); sent once more without a new round`
            : h.failed
              ? `- ${h.round} repair from ${h.base} failed: ${h.failed} (the round was consumed)`
              : `- ${h.round} repair from ${h.base} to ${h.candidate}: ${h.stop ? `stopped (${h.stop.reason})` : h.summary}; checks `
                + `${h.checks.passed ? "pass" : "fail"}: ${h.checks.summary}${h.addsRequiredFix ? "; adds a required fix" : ""}; dispositions `
                + `${h.dispositions.map((d) => `${d.id} ${d.disposition}: ${d.note}`).join(" | ") || "none"}`
                + (h.verification ? `; verification ${h.verification.verified ? "passed" : "failed"}: ${h.verification.summary}` : ""))),
        "",
        test ? "" : `Continue with skills/${skill}/SKILL.md from its delivery step, using this result. Write the ledger below to your score ledger and render the chart.`,
        `Scores round to ${decimalsOf(p.scale)} decimal place(s).${p.continuation ? " The ledger includes every earlier run of this continuation." : ""}`,
        "Score ledger:", JSON.stringify(ledger),
        continueWith ? `Continuation fields for an approved continuation from the latest candidate ${latest.candidate} (write the approval and change; priorLedger is the score ledger above):` : "",
        continueWith ? JSON.stringify({ ...continueWith, priorLedger: "<the score ledger above>" }) : "",
      ]);
      return result;
    }),
);
