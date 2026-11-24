// @tested-t3 0.1.12-nightly.20261123.5151
// @start manual
//
// Durable bookkeeping for skills/review-loop/SKILL.md and skills/hillclimb/SKILL.md:
// the judge roster and reviewer selection, frozen candidates, the score metric,
// the target, check and coverage gate, panel entry, the two-non-improving-rounds
// stop, the one retry of a failed evaluation, explicit limits, required-fix
// eligibility, the single automatic recovery and the score ledger. Judgment stays
// in agent steps: judges score in fresh read-only threads; the invoking thread
// repairs, reports host receipts and diagnoses the recovery.
//
// Start: POST a JSON packet to this workflow's `start` webhook with an
// `idempotency-key` header; the same key returns the same run. The invoking
// thread gets a turn for selection data, after each evaluation (receipts), one
// per repair, one for the recovery when it is needed, and the result. The hook
// URL lives in a private curl config; never put it in a command line, a
// transcript or this file.
//
// At-most-once dispatch (REC-01): every judge, repair and recovery dispatch is a
// keyed agent step. T3 journals each start under `<run>/<step>/<round>` and
// derives the turn from that key, so a restart or reload replays the recorded
// turn instead of starting another. The recovery has one step key per run, and
// a continuation packet (an operator-approved new run) carries the spent slot,
// so no run family gets a second automatic recovery.

const MODES = ["approval-required", "auto-accept-edits", "auto", "full-access"];
const MODE_RANK = { "approval-required": 0, "auto-accept-edits": 1, auto: 2, "full-access": 3 };

// Judge routes. `standing` routes are review's static order (model-selection.md).
// Grok 4.7 is in that order but has no route here: its T3 provider is disabled on
// the tested host and its model ID is unverified, so selection reports it as
// unavailable rather than guessing. Add it here once the route is verified.
// `scoring` routes need a confirmed hillclimb roster; `named` routes need the operator's choice.
const ROUTES = {
  sol: { label: "Sol 6.2 high", instanceId: "codex", model: "gpt-6.2-sol", effort: { id: "reasoningEffort", value: "high" }, lineage: "openai", standing: true },
  opus: { label: "Opus 5.5 high", instanceId: "claudeAgent", model: "claude-opus-5-5", effort: { id: "effort", value: "high" }, lineage: "anthropic", standing: true },
  "sonnet-agy": { label: "Sonnet 5.5 high via AGY", instanceId: "antigravity", model: "claude-sonnet-5-5", effort: { id: "thought_level", value: "high" }, lineage: "anthropic", standing: true, minMode: "auto-accept-edits" },
  neon: { label: "Neon 4 high", instanceId: "antigravity", model: "gemini-4-neon", effort: { id: "thought_level", value: "high" }, lineage: "google", standing: true, minMode: "auto-accept-edits" },
  hydrogen: { label: "Hydrogen 4 high", instanceId: "antigravity", model: "gemini-4-hydrogen", effort: { id: "thought_level", value: "high" }, lineage: "google", standing: true, minMode: "auto-accept-edits" },
  deepseek: { label: "DeepSeek Flash V4.1 high", instanceId: "opencode", model: "litellm/deepseek-v4.1-flash", effort: { id: "variant", value: "high" }, lineage: "deepseek", scoring: true, minMode: "full-access" },
  "opus-xhigh": { label: "Opus 5.5 xhigh", instanceId: "claudeAgent", model: "claude-opus-5-5", effort: { id: "effort", value: "xhigh" }, lineage: "anthropic", named: true },
  fable: { label: "Fable 5.2 high", instanceId: "claudeAgent", model: "claude-fable-5-2", effort: { id: "effort", value: "high" }, lineage: "anthropic", named: true },
};
const ROUTE_KEYS = Object.keys(ROUTES);
const STATIC_ORDER = ["sol", "opus", "sonnet-agy", "neon", "hydrogen"];
const LINEAGES = ["anthropic", "openai", "google", "deepseek", "xai", "qwen", "other"];
const SEVERITIES = ["SEV1", "SEV2", "SEV3"];
const HOME = process.env.HOME;
const CARD = `${HOME}/.agents/skills/review/references/assigned-reviewer.md`;
const NO_DEADLINE = Number.POSITIVE_INFINITY;

// ---------- schemas ----------

const Checks = Schema.Struct({ passed: Schema.Boolean, coverage: Schema.Boolean, summary: Schema.String });
const Route = Schema.Literals(ROUTE_KEYS);

const Roster = Schema.Struct({
  primary: Schema.optional(Route),
  panel: Schema.optional(Schema.Array(Route)),
  panelTrigger: Schema.optional(Schema.Literals(["target", "baseline"])),
  panelPrimary: Schema.optional(Route),
  companions: Schema.optional(Schema.Array(Route)),
  overlapApproved: Schema.optional(Schema.Boolean),
});

const SyntheticRecovery = Schema.Struct({
  outcome: Schema.Literals(["fixed", "fix-failed"]),
  target: Schema.optional(Schema.Number),
  // The fix changes the candidate (and so consumes a repair round).
  changes: Schema.optional(Schema.Boolean),
});

const Test = Schema.Struct({
  // One entry per evaluation (and per retry), in order: each scoring judge's score, or null for a failure.
  scores: Schema.Array(Schema.Array(Schema.NullOr(Schema.Number))),
  // Repair rounds (1-based, across the run) whose synthetic candidate fails checks, cannot build,
  // adds a required fix, or resubmits the repair base.
  failChecks: Schema.optional(Schema.Array(Schema.Number)),
  unbuildable: Schema.optional(Schema.Array(Schema.Number)),
  requiredFix: Schema.optional(Schema.Array(Schema.Number)),
  resubmit: Schema.optional(Schema.Array(Schema.Number)),
  // Evaluations (1-based) whose judges report a coverage gap.
  coverageGap: Schema.optional(Schema.Array(Schema.Number)),
  // A synthetic recovery; leave it out to ask the invoking thread for a real one.
  recovery: Schema.optional(SyntheticRecovery),
  // Pause the run at these named points until pauseSeconds after each first runs.
  pauseAt: Schema.optional(Schema.Array(Schema.Literals(["before-recovery", "after-recovery", "after-baseline"]))),
  pauseSeconds: Schema.optional(Schema.Number),
});

const Continuation = Schema.Struct({
  // The stopped run this operator-approved continuation follows. Its automatic recovery is spent.
  priorRun: Schema.String,
  // Repair rounds the prior run already consumed against the same explicit limit.
  repairsUsed: Schema.Number,
  approval: Schema.String,
  // The prior run's final score ledger as JSON text; its eras and rounds are kept as history
  // when its scale matches. Prior scores are never reused: the baseline is always re-evaluated.
  priorLedger: Schema.optional(Schema.String),
  // True when the rubric, target, checks and roster are unchanged, so the chart compares the eras.
  sameContract: Schema.Boolean,
});

const Packet = Schema.Struct({
  invokerThread: Schema.String,
  skill: Schema.Literals(["review-loop", "hillclimb"]),
  title: Schema.String,
  // T3 project ID or registered path for judge threads; judges read the checkout by path.
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
  scale: Schema.Struct({ min: Schema.Number, max: Schema.Number, precision: Schema.Number }),
  // Model families that materially wrote the code, repairers included.
  codeAuthors: Schema.Array(Schema.Literals(LINEAGES)),
  // Permitted checks, commands, scratch directory and evidence requirements for judges.
  reviewContext: Schema.String,
  roster: Schema.optional(Roster),
  limits: Schema.optional(Schema.Struct({
    repairRounds: Schema.optional(Schema.Number),
    deadline: Schema.optional(Schema.String),
    // An explicit spend cap, as the operator stated it. The workflow cannot measure spend:
    // the invoking thread reports reaching it, and a reached cap blocks the recovery.
    spendCap: Schema.optional(Schema.String),
  })),
  continuation: Schema.optional(Continuation),
  // The project adopted `review_rounds: 1` (skills/review/references/single-round.md): one scored
  // review, then coordinator-verified repairs and no recheck.
  singleRound: Schema.optional(Schema.Boolean),
  judgeMinutes: Schema.optional(Schema.Number),
  repairMinutes: Schema.optional(Schema.Number),
  test: Schema.optional(Test),
});
const decodePacket = Schema.decodeUnknownSync(Packet);

const Finding = Schema.Struct({
  id: Schema.String,
  severity: Schema.Literals(SEVERITIES),
  title: Schema.String,
  location: Schema.String,
  evidence: Schema.String,
  impact: Schema.String,
});
const Dimension = Schema.Struct({ name: Schema.String, score: Schema.Number, weight: Schema.optional(Schema.Number) });
const Judged = Schema.Struct({
  revision: Schema.String,
  score: Schema.NullOr(Schema.Number),
  bullets: Schema.Array(Schema.String),
  dimensions: Schema.optional(Schema.Array(Dimension)),
  findings: Schema.Array(Finding),
  // False when a required check, state or piece of evidence could not be covered.
  coverageComplete: Schema.Boolean,
  coverageGaps: Schema.String,
  model: Schema.String,
});
const Repair = Schema.Struct({
  candidate: Schema.String,
  checks: Checks,
  buildable: Schema.Boolean,
  // True when this candidate adds a fix every later candidate must keep.
  addsRequiredFix: Schema.Boolean,
  summary: Schema.String,
  dispositions: Schema.Array(Schema.Struct({
    id: Schema.String,
    disposition: Schema.Literals(["fixed", "deferred", "rejected", "open"]),
    note: Schema.String,
  })),
  // Null, or why no repair could be made; `limit` names an exhausted explicit limit.
  stop: Schema.NullOr(Schema.Struct({ reason: Schema.String, limit: Schema.Literals(["none", "spend-cap", "deadline"]) })),
  // Single-round runs only: whether the coordinator verified every accepted repair, and how.
  verification: Schema.NullOr(Schema.Struct({ verified: Schema.Boolean, summary: Schema.String })),
  // Refreshed availability and spend cap: this turn precedes the next judge dispatch.
  unavailableRoutes: Schema.Array(Schema.String),
  spendCapReached: Schema.Boolean,
});
const Fix = Schema.Struct({
  outcome: Schema.Literals(["fixed", "fix-failed"]),
  diagnosis: Schema.String,
  fix: Schema.String,
  candidate: Schema.String,
  checks: Checks,
  buildable: Schema.Boolean,
  revised: Schema.NullOr(Schema.Struct({
    reason: Schema.String,
    target: Schema.optional(Schema.Number),
    rubric: Schema.optional(Schema.String),
    criteria: Schema.optional(Schema.String),
    // The changed loop-required checks, described.
    checks: Schema.optional(Schema.String),
    primary: Schema.optional(Route),
    panel: Schema.optional(Schema.Array(Route)),
  })),
  // Refreshed availability: route keys whose provider is unavailable or lacks the exact model now.
  unavailableRoutes: Schema.Array(Schema.String),
  spendCapReached: Schema.Boolean,
});
const Pace = Schema.Struct({
  observedAt: Schema.String,
  providers: Schema.Array(Schema.Struct({
    provider: Schema.String,
    paceScore: Schema.NullOr(Schema.Number),
    paceBasis: Schema.NullOr(Schema.String),
    available: Schema.Boolean,
  })),
  // Route keys whose provider does not list the route's exact model or effort option.
  unavailableRoutes: Schema.Array(Schema.String),
  // True when the run's explicit spend cap is already reached; no judge is dispatched.
  spendCapReached: Schema.Boolean,
});
// Every judge dispatch after the first follows one of these turns, which refresh availability and the cap.
const Receipts = Schema.Struct({
  judges: Schema.Array(Schema.Struct({
    thread: Schema.String,
    turnId: Schema.NullOr(Schema.String),
    executedModel: Schema.NullOr(Schema.String),
    turns: Schema.NullOr(Schema.Number),
  })),
  unavailableRoutes: Schema.Array(Schema.String),
  spendCapReached: Schema.Boolean,
});

// Words that name a model family in a judge's own identity claim.
const FAMILY_WORDS = {
  openai: ["gpt", "sol", "openai", "codex", "chatgpt"],
  anthropic: ["claude", "opus", "sonnet", "fable", "haiku", "anthropic"],
  google: ["gemini", "neon", "hydrogen", "argon", "carbon", "google"],
  deepseek: ["deepseek"],
  xai: ["grok", "xai"],
  qwen: ["qwen"],
};

// ---------- pure rules (no clock, no I/O) ----------

function decimals(precision) {
  const text = String(precision);
  return text.includes(".") ? text.split(".")[1].length : 0;
}

// The rubric's fixed precision, kept inside the scale.
function quantise(score, scale) {
  const stepped = Number((Math.round(score / scale.precision) * scale.precision).toFixed(decimals(scale.precision)));
  return Math.min(scale.max, Math.max(scale.min, stepped));
}

function modeOf(route, ceiling) {
  // A judge runs in the invoker's own mode, the way a delegated reviewer inherits it,
  // unless its route needs a broader one; then the route is skipped.
  return route.minMode !== undefined && MODE_RANK[route.minMode] > MODE_RANK[ceiling] ? null : ceiling;
}

function sameRevision(a, b) {
  const x = String(a ?? "").trim().toLowerCase();
  const y = String(b ?? "").trim().toLowerCase();
  return x.length >= 7 && y.length >= 7 && (x.startsWith(y) || y.startsWith(x));
}

function lineageBlocked(p, key) {
  return p.scope === "code" && p.codeAuthors.includes(ROUTES[key].lineage);
}

function targetFits(scale, target) {
  return typeof target === "number" && target > scale.min && target <= scale.max;
}

function rosterKeys(r) {
  return [r.primary, r.panelPrimary, ...(r.panel ?? []), ...(r.companions ?? [])].filter(Boolean);
}

function packetProblems(p) {
  const problems = [];
  for (const field of ["invokerThread", "title", "project", "checkout", "base", "candidate", "criteria", "rubric"]) {
    if (!String(p[field]).trim()) problems.push(`${field} is empty`);
  }
  if (!p.checkout.startsWith("/")) problems.push("checkout must be an absolute path");
  const s = p.scale;
  if (!(s.precision > 0) || !(s.max > s.min)) problems.push("scale needs min < max and a positive precision");
  if (decimals(s.precision) > 3) problems.push("scale.precision may have at most three decimal places");
  if (!targetFits(s, p.target)) problems.push("target must sit inside the scale");
  const r = p.roster ?? {};
  const scoring = [r.primary, r.panelPrimary, ...(r.panel ?? [])].filter(Boolean);
  const panelSeats = [r.panelPrimary ?? r.primary, ...(r.panel ?? [])].filter(Boolean);
  if (new Set(panelSeats).size !== panelSeats.length) problems.push("a panel seat repeats; each panel judge is a distinct route");
  if (p.skill === "hillclimb") {
    if (r.primary === undefined) problems.push("hillclimb needs its confirmed roster: roster.primary");
    if (p.singleRound === true) problems.push("review_rounds: 1 does not replace hillclimb's own scores; leave singleRound out");
  } else {
    // Companions add findings, not a score; visual judgments carry no lineage exclusion.
    for (const key of scoring) {
      if (ROUTES[key].scoring) problems.push(`${key} scores only in a confirmed hillclimb roster`);
      if (lineageBlocked(p, key)) problems.push(`${key} shares the ${ROUTES[key].lineage} lineage with a code author; name an eligible reviewer`);
    }
    if ((r.panel ?? []).length > 0 || r.panelPrimary !== undefined || r.panelTrigger !== undefined) {
      problems.push("panel settings belong to hillclimb");
    }
  }
  for (const key of rosterKeys(r)) {
    if (modeOf(ROUTES[key], p.maxRuntimeMode) === null) {
      problems.push(`${key} needs ${ROUTES[key].minMode}, above the invoker's ${p.maxRuntimeMode}`);
    }
  }
  const lim = p.limits ?? {};
  if (lim.repairRounds !== undefined && !(Number.isInteger(lim.repairRounds) && lim.repairRounds >= 0)) {
    problems.push("limits.repairRounds must be a whole number");
  }
  if (lim.deadline !== undefined && !Number.isFinite(Date.parse(lim.deadline))) problems.push("limits.deadline must be an ISO 8601 time");
  const c = p.continuation;
  if (c !== undefined) {
    if (!c.priorRun.trim() || !c.approval.trim()) problems.push("continuation needs priorRun and the operator's approval");
    if (!(Number.isInteger(c.repairsUsed) && c.repairsUsed >= 0)) problems.push("continuation.repairsUsed must be a whole number");
    if (c.priorLedger !== undefined && priorLedgerOf(c.priorLedger) === null) problems.push("continuation.priorLedger is not a version 1 score ledger");
  }
  return problems;
}

// Other models a judge's claim may name inside its own family; naming one conflicts with the route.
const SIBLINGS = {
  sol: ["terra", "luna", "astra"],
  opus: ["sonnet", "haiku", "fable"],
  "sonnet-agy": ["opus", "haiku", "fable"],
  neon: ["hydrogen", "argon", "carbon", "flash"],
  hydrogen: ["neon", "argon", "carbon", "flash"],
  deepseek: ["qwen", "glm"],
  "opus-xhigh": ["sonnet", "haiku", "fable"],
  fable: ["opus", "sonnet", "haiku"],
};
const EFFORT_WORDS = ["minimal", "low", "medium", "high", "xhigh", "max", "ultra", "ultrathink"];
// The version each route's model carries; a claimed version next to a family word must match it.
const VERSIONS = { sol: "6.2", opus: "5.5", "sonnet-agy": "5.5", neon: "4", hydrogen: "4", deepseek: "4.1", "opus-xhigh": "5.5", fable: "5.2" };

// A judge's own claim conflicts when it names another family and not its own, another model in its
// family, or an effort other than its route's. Returns the conflicts, or null.
function identityConflict(key, claim) {
  const text = String(claim ?? "").toLowerCase();
  const route = ROUTES[key];
  const has = (w) => new RegExp(`(^|[^a-z])${w}([^a-z]|$)`).test(text);
  const conflicts = [];
  const others = Object.keys(FAMILY_WORDS).filter((f) => f !== route.lineage && FAMILY_WORDS[f].some(has));
  if (others.length > 0 && !(FAMILY_WORDS[route.lineage] ?? []).some(has)) conflicts.push(`names ${others.join(", ")}`);
  const siblings = (SIBLINGS[key] ?? []).filter(has);
  if (siblings.length > 0) conflicts.push(`names ${siblings.join(", ")}`);
  // Any effort word other than the route's, standing alone, is a conflicting setting.
  const efforts = EFFORT_WORDS.filter((w) => w !== route.effort.value && has(w));
  if (efforts.length > 0) conflicts.push(`reports effort ${efforts.join(", ")}`);
  // A version written next to a family word, as in "GPT-6.1" or "Opus 4.6", must be the route's.
  const family = (FAMILY_WORDS[route.lineage] ?? []).join("|");
  const versions = [...text.matchAll(new RegExp(`(?:${family})[\\s-]*v?(\\d+(?:\\.\\d+)?)`, "g"))].map((m) => m[1]);
  const wrong = versions.filter((v) => v !== VERSIONS[key]);
  if (wrong.length > 0 && !versions.includes(VERSIONS[key])) conflicts.push(`reports version ${wrong.join(", ")}`);
  return conflicts.length > 0 ? conflicts : null;
}

// Keep only dimensions the score chart accepts: a name and, when weighted, a positive weight.
function cleanDimensions(dimensions, scale) {
  return (dimensions ?? []).filter((d) => d.name.trim() && d.score >= scale.min && d.score <= scale.max
    && (d.weight === undefined || d.weight > 0)).map((d) => ({ ...d, name: d.name.trim() }));
}

// A prior run's ledger, parsed, or null when it is not a version 1 ledger.
function priorLedgerOf(text) {
  try {
    const l = JSON.parse(text);
    return l && l.version === 1 && Array.isArray(l.eras) && Array.isArray(l.rounds) && Array.isArray(l.reviewers) ? l : null;
  } catch {
    return null;
  }
}

// Review's selection rule: after the gates, the highest-scored provider wins; null is
// unknown and cannot win; with no scored candidate, keep the static order.
function selectPrimary(p, pace) {
  const gates = [];
  const missing = new Set(pace?.unavailableRoutes ?? []);
  const eligible = STATIC_ORDER.filter((key) => {
    const route = ROUTES[key];
    if (lineageBlocked(p, key)) {
      gates.push(`${key}: ${route.lineage} wrote code`);
      return false;
    }
    if (modeOf(route, p.maxRuntimeMode) === null) {
      gates.push(`${key}: needs ${route.minMode}`);
      return false;
    }
    const seen = pace?.providers.find((x) => x.provider === route.instanceId);
    if (seen !== undefined && !seen.available) {
      gates.push(`${key}: provider ${route.instanceId} unavailable`);
      return false;
    }
    if (missing.has(key)) {
      gates.push(`${key}: ${route.instanceId} does not list ${route.model}`);
      return false;
    }
    return true;
  });
  gates.push("grok: no verified T3 route on this host");
  if (eligible.length === 0) return { order: [], basis: "no eligible reviewer", gates };
  const scored = eligible
    .map((key) => ({ key, pace: pace?.providers.find((x) => x.provider === ROUTES[key].instanceId) }))
    .filter((x) => typeof x.pace?.paceScore === "number");
  if (scored.length === 0) {
    return { order: eligible, basis: pace ? "no eligible provider has a paceScore; static order, capacity unknown" : "pace snapshot unavailable; static order, capacity unknown", gates };
  }
  // Highest provider first; inside a provider keep static order; unscored providers follow in static order.
  const byScore = [...scored].sort((a, b) => b.pace.paceScore - a.pace.paceScore || STATIC_ORDER.indexOf(a.key) - STATIC_ORDER.indexOf(b.key));
  const order = [...new Set([...byScore.map((x) => x.key), ...eligible])];
  const top = byScore[0];
  return { order, basis: `${top.key}: ${top.pace.provider} paceScore ${top.pace.paceScore} (${top.pace.paceBasis ?? "basis not reported"}) at ${pace.observedAt}`, gates };
}

function judgedProblems(p, candidate, v, scoring) {
  const problems = [];
  if (!sameRevision(v.revision, candidate)) problems.push(`reviewed revision ${v.revision} is not the frozen candidate ${candidate}`);
  if (scoring) {
    const s = p.scale;
    if (typeof v.score !== "number" || !Number.isFinite(v.score) || v.score < s.min || v.score > s.max) problems.push(`score must be a number from ${s.min} to ${s.max}`);
    const bullets = v.bullets.filter((b) => b.trim());
    if (bullets.length < 3 || bullets.length > 5) problems.push("rationale needs 3 to 5 bullets");
    for (const d of v.dimensions ?? []) {
      if (!(d.score >= s.min && d.score <= s.max)) problems.push(`dimension ${d.name} is outside the scale`);
    }
  }
  return problems;
}

// One evaluation's metric: the lowest scoring judge, quantised to the rubric precision.
function metricOf(p, judges) {
  const scores = judges.filter((j) => j.scoring).map((j) => j.score);
  if (scores.length === 0 || scores.some((x) => typeof x !== "number")) return null;
  return quantise(Math.min(...scores), p.scale);
}

function complete(judges) {
  return judges.every((j) => j.status === "scored" || j.status === "reported");
}

// Every judge, companions included, must report complete coverage.
function judgesCovered(judges) {
  return judges.every((j) => j.coverageComplete !== false);
}

function gatePasses(target, metric, checks, covered) {
  return metric !== null && metric >= target && checks.passed && checks.coverage && covered;
}

// The progress rule after a gate test: only a strict increase over the historical best resets.
function progress(state, metric) {
  if (metric !== null && (state.best === null || metric > state.best.metric)) return { improved: true, counter: 0 };
  return { improved: false, counter: state.counter + 1 };
}

// The best candidate that keeps every required fix: seq at or after the floor; the earlier wins a tie.
function eligibleBest(scored, floor) {
  let best = null;
  for (const c of scored) {
    if (c.seq >= floor && c.metric !== null && (best === null || c.metric > best.metric)) best = c;
  }
  return best;
}

// The candidate an incomplete stop hands back, under the rounds rules. `floor` is the required-fix
// floor seq and `floorCandidate` the candidate that set it.
function finalCandidate(eras, floor, floorCandidate) {
  const last = eras[eras.length - 1];
  const fallback = (candidate, seq, note) => (seq >= floor
    ? { candidate, metric: null, note, entry: null }
    : { candidate: floorCandidate, metric: null, note: `${note}; it lacks a required fix, so the required-fix candidate is handed back`, entry: null });
  // A panel phase that never completed a panel score in this invocation hands back its panel entry.
  if (last.phase === "panel" && !last.scored.some((c) => c.phase === "panel")) {
    return fallback(last.panelEntry ?? last.latest, last.panelEntrySeq ?? last.latestSeq, "panel-entry candidate; no complete panel result");
  }
  const comparable = eras.every((e) => e.comparable && e.phase === last.phase);
  const pool = (comparable ? eras : [last]).flatMap((e) => e.scored.filter((c) => c.phase === last.phase));
  const best = eligibleBest(pool, floor);
  if (best !== null) {
    return { candidate: best.candidate, metric: best.metric, entry: best,
      note: comparable ? "best fully scored candidate that keeps required fixes" : "best under the current contract; earlier scores historical" };
  }
  return fallback(last.latest, last.latestSeq, "no ranked best; latest eligible work (the era's frozen baseline or later)");
}

function ledgerOf(p, runId, status, eras, rounds, rosterLabels, prior) {
  const own = Object.entries(rosterLabels).map(([id, x]) => ({ id, label: x.label, role: x.role }));
  // Prior history renders only on the same scale; otherwise it stays in the prior run's own ledger.
  const s = prior?.run?.scale;
  if (prior && !(s && s.min === p.scale.min && s.max === p.scale.max)) prior = null;
  // A continuation keeps the prior run's eras and rounds as history, ahead of its own.
  const priorReviewers = (prior?.reviewers ?? []).filter((r) => !own.some((o) => o.id === r.id));
  const reviewers = [...priorReviewers, ...own];
  const priorEras = (prior?.eras ?? []).map((e) => ({ ...e, id: `p-${e.id}`, label: `Prior run: ${e.label}`, historical: true }));
  const priorRounds = (prior?.rounds ?? []).map((r) => ({ ...r, id: `P-${r.id}`, era: `p-${r.era}` }));
  const scale = { min: p.scale.min, max: p.scale.max, precision: decimals(p.scale.precision) };
  return {
    version: 1,
    // The ledger's precision is decimal places; the packet's is the rubric's step.
    run: { title: p.title, id: runId, skill: p.skill, status, scale },
    reviewers: reviewers.length ? reviewers : [{ id: "none", label: "no judge" }],
    eras: [...priorEras, ...eras.map((e, i) => ({
      id: `e${i + 1}`,
      label: i === 0 ? (p.continuation ? "Continuation" : "Original contract") : `Recovery era ${i + 1}`,
      target: e.target,
      ...(e.target !== p.target ? { original_target: p.target } : {}),
      historical: i < eras.length - 1 && !eras[i + 1].comparable,
      comparable_to_prev: i === 0 ? (priorEras.length > 0 && p.continuation?.sameContract === true) : e.comparable,
      ...(e.recovery ? { recovery: e.recovery } : {}),
    }))],
    rounds: [...priorRounds, ...(rounds.length ? rounds : [{ id: "B0", label: "Baseline", era: "e1", phase: "primary",
      expected_reviewers: [reviewers.length ? reviewers[reviewers.length - 1].id : "none"], status: "unscored",
      failure_note: "no evaluation completed", scores: [] }])],
  };
}

function roundEntry(p, eraIndex, label, id, candidate, phase, judges, failure) {
  const scoring = judges.filter((j) => j.scoring);
  const scores = scoring.map((j) => {
    const retry = j.retried ? { retried: true, retry_note: j.retryNote } : {};
    const dims = cleanDimensions(j.dimensions, p.scale);
    return typeof j.score === "number"
      ? { reviewer: j.key, score: quantise(j.score, p.scale), bullets: j.bullets.map((b) => b.trim()).filter(Boolean).slice(0, 5),
        ...(dims.length ? { dimensions: dims } : {}), ...retry }
      : { reviewer: j.key, score: null, status: j.status, failure_note: j.problems.join("; ") || j.status, ...retry };
  });
  const status = failure ? (scores.some((s) => s.score !== null) ? "incomplete" : "unscored")
    : scores.every((s) => s.score !== null) ? "scored" : "incomplete";
  return {
    id, label, candidate, era: `e${eraIndex + 1}`, phase,
    expected_reviewers: scoring.map((j) => j.key),
    status,
    ...(status === "scored" ? {} : { failure_note: failure ?? "a judge returned no score" }),
    scores,
  };
}

function findingsText(judges, withEvidence) {
  const lines = [];
  for (const j of judges) {
    for (const f of j.findings ?? []) {
      lines.push(`- ${j.key}/${f.id} ${f.severity} ${f.title} @ ${f.location}: ${f.impact}`
        + (withEvidence ? `\n  evidence: ${f.evidence.slice(0, 400)}` : ""));
    }
    if (j.coverageComplete === false) lines.push(`- ${j.key} coverage gap: ${String(j.coverageGaps ?? "").slice(0, 400)}`);
  }
  return lines.length ? lines.join("\n") : "- none reported";
}

function receiptsText(judges) {
  return judges.filter((j) => j.thread).map((j) => `- ${j.key}: thread ${j.thread}, turn ${j.executed?.turnId ?? "unknown"}, `
    + `requested ${ROUTES[j.key].model} ${ROUTES[j.key].effort.id}=${ROUTES[j.key].effort.value}, `
    + `executedModel ${j.executed?.model ?? "null"} (${j.executed?.verified ? "verified" : "unverified"}), effort unverified `
    + `(the host records none), self-reported "${String(j.claim ?? "").slice(0, 80)}"`).join("\n") || "- none";
}

// ---------- workflow ----------

export default T3.workflow(
  "scored-loop",
  { version: 5, payload: T3.WebhookRequest, triggers: [T3.webhook("start")] },
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
          yield* T3.agent("callback", { thread: { threadId: thread }, brief: [
            `[T3 workflow scored-loop, run ${id}]`,
            "Packet rejected before any judge was dispatched. Nothing was scored.",
            `- ${parsed.reason.slice(0, 600)}`,
            "Fix the packet and start again with a new idempotency key.",
          ].join("\n") });
        }
        return yield* T3.stop(`packet rejected: ${parsed.reason}`);
      }
      const p = parsed.value;
      const test = p.test !== undefined;
      yield* T3.title(`${test ? "[test] " : ""}${p.skill}: ${p.title.slice(0, 80)}`);
      const head = `[T3 workflow scored-loop (${p.skill}), run ${id}]`;
      const tell = (name, lines) => T3.agent(name, { thread: { threadId: p.invokerThread }, brief: [head, ...lines].join("\n") });

      const problems = packetProblems(p);
      if (problems.length > 0) {
        yield* tell("callback", ["Packet rejected; no judge was dispatched.", ...problems.map((x) => `- ${x}`),
          "Fix the packet and start again with a new idempotency key."]);
        return { run: id, outcome: "rejected", problems };
      }

      // ----- clock and limits -----
      const now = (name) => T3.step(name, { returns: Schema.Number }, Effect.sync(() => Date.now()));
      const deadline = p.limits?.deadline !== undefined ? Date.parse(p.limits.deadline) : NO_DEADLINE;
      const roundCap = p.limits?.repairRounds ?? null;
      const judgeMs = Math.round((p.judgeMinutes ?? 60) * 60000);
      const repairMs = Math.round((p.repairMinutes ?? 240) * 60000);
      // Every agent step's time, capped by the run deadline. Zero or less means the deadline passed.
      // Read fresh, not journaled: after a restart the time left is measured again, so a dispatch
      // never runs on an allowance taken before the deadline. `name` labels the call site only.
      const allowance = (name, wanted) =>
        Effect.sync(() => (deadline === NO_DEADLINE ? wanted : Math.min(wanted, deadline - Date.now())));
      const pauses = new Set(p.test?.pauseAt ?? []);
      const pausePoint = (name) => pauses.has(name)
        ? Effect.gen(function* () {
          const armed = yield* now(`test/${name}/armed`);
          yield* T3.step(`test/${name}`, { returns: Schema.Number }, Effect.suspend(() => {
            const wait = armed + (p.test.pauseSeconds ?? 60) * 1000 - Date.now();
            return wait > 0 ? Effect.fail(new Error(`test pause at ${name}: resume after ${Math.ceil(wait / 1000)} more second(s)`)) : Effect.succeed(Date.now());
          }));
        })
        : Effect.void;

      // ----- roster and selection data -----
      const r = p.roster ?? {};
      const routeList = ROUTE_KEYS.map((k) => `- ${k}: ${ROUTES[k].instanceId}/${ROUTES[k].model} with ${ROUTES[k].effort.id}=${ROUTES[k].effort.value}`);
      const capLine = p.limits?.spendCap ? `Report spendCapReached true if this spend cap is reached: ${p.limits.spendCap}.` : "Report spendCapReached false.";
      let pace = null;
      let paceProblem = test ? "test run: static order" : null;
      if (!test) {
        const left = yield* allowance("select/clock", 10 * 60000);
        const paced = left <= 0 ? { outcome: "failed", reason: "the run deadline passed" } : yield* T3.agent.try("select", {
          thread: { threadId: p.invokerThread },
          timeout: `${left} millis`,
          returns: Pace,
          brief: [
            `${head} Reviewer selection data. Do nothing else in this turn.`,
            "Call the limits MCP tool limits-limits_snapshot with detail \"brief\" and orchestrator_capabilities.",
            "For each provider instance codex, claudeAgent, antigravity and opencode, report its paceScore and",
            "paceBasis (null when the snapshot has none) and whether orchestrator_capabilities lists it as available.",
            "Report as unavailableRoutes each route key below whose provider does not list its exact model and effort option:",
            ...routeList,
            capLine,
            "Report the snapshot's observation time as observedAt. Submit with t3_submit_output.",
          ].join("\n"),
        });
        if (paced.outcome === "done") pace = paced.value;
        else paceProblem = paced.reason.slice(0, 200);
      }
      // The latest availability snapshot and spend-cap report; each later invoker turn refreshes them.
      const offRoutes = (routes, providers) => new Set([...(routes ?? []),
        ...ROUTE_KEYS.filter((k) => (providers ?? []).some((x) => !x.available && x.provider === ROUTES[k].instanceId))]);
      let unavailable = offRoutes(pace?.unavailableRoutes, pace?.providers);
      let capReached = pace?.spendCapReached === true;
      // Judges dispatch only while the latest invoker turn established route availability. A failed
      // selection, receipts, repair or recovery turn leaves it unknown until the next one succeeds.
      let availabilityKnown = test || pace !== null;
      const refresh = (value) => {
        if (value === null) {
          availabilityKnown = false;
          return;
        }
        unavailable = offRoutes(value.unavailableRoutes, []);
        capReached = capReached || value.spendCapReached === true;
        availabilityKnown = true;
      };
      const prior = p.continuation?.priorLedger !== undefined ? priorLedgerOf(p.continuation.priorLedger) : null;
      if (capReached) {
        yield* tell("callback", [`Spend cap reached before any judge was dispatched: ${p.limits?.spendCap ?? "as reported"}. Nothing was scored.`]);
        return { run: id, outcome: "blocked", problems: ["spend cap reached"] };
      }
      const namedMissing = rosterKeys(r).filter((k) => unavailable.has(k));
      if (namedMissing.length > 0) {
        yield* tell("callback", ["Roster unavailable: these named routes are not offered by their providers now.",
          ...namedMissing.map((k) => `- ${k}: ${ROUTES[k].instanceId}/${ROUTES[k].model}`),
          "Ask the operator for an eligible alternative, then start again with a new idempotency key."]);
        return { run: id, outcome: "blocked", problems: namedMissing };
      }
      let selection = null;
      let primary = r.primary ?? null;
      if (primary === null) {
        selection = selectPrimary(p, pace);
        if (paceProblem) selection.basis += ` (selection data: ${paceProblem})`;
        primary = selection.order[0] ?? null;
      }
      if (primary === null) {
        yield* tell("callback", ["No eligible reviewer: hold dependent review for the operator's choice.",
          ...(selection?.gates ?? []).map((g) => `- ${g}`)]);
        return { run: id, outcome: "blocked", selection };
      }
      const panelKeys = r.panel ?? [];
      const companions = r.companions ?? [];
      const confirmed = new Set(rosterKeys(r));
      const overlaps = p.skill === "hillclimb"
        ? [primary, r.panelPrimary, ...panelKeys].filter(Boolean).filter((k) => lineageBlocked(p, k))
        : [];
      if (overlaps.length > 0 && r.overlapApproved !== true) {
        yield* tell("callback", ["Roster rejected: these scoring seats share a lineage with a code author and the overlap is not approved.",
          ...overlaps.map((k) => `- ${k} (${ROUTES[k].lineage})`), "Confirm the overlap with the operator or change the roster, then start again."]);
        return { run: id, outcome: "rejected", problems: ["unapproved lineage overlap"] };
      }

      // Judges for a phase: the primary alone, or the panel (with any approved panel primary).
      // The roster never changes inside an era; only a declared recovery revision changes it.
      const seatsFor = (phase, roster) => {
        const scoringKeys = phase === "panel" ? [roster.panelPrimary ?? roster.primary, ...roster.panel] : [roster.primary];
        return [...scoringKeys.map((key, i) => ({ key, scoring: true, role: phase === "panel" ? (i === 0 ? "Panel primary" : "Panel") : "Primary" })),
          ...companions.map((key) => ({ key, scoring: false, role: "Companion" }))];
      };
      const rosterLabels = {};
      const label = (seat) => {
        rosterLabels[seat.key] = { label: ROUTES[seat.key].label, role: seat.role };
      };

      // ----- one judge, one evaluation -----
      const priorFindings = {};
      let evalCount = 0;
      let synthetic = 0;
      const judgeOnce = (key, seat, candidate, phase, contract, note) =>
        Effect.gen(function* () {
          const route = ROUTES[seat.key];
          const mode = modeOf(route, p.maxRuntimeMode);
          // No dispatch past a reached spend cap or to a route the latest snapshot lists as unavailable.
          if (capReached) return { ...seat, status: "limit", score: null, problems: ["the spend cap is reached"], thread: null, limit: "spend-cap" };
          if (!availabilityKnown) return { ...seat, status: "unavailable", score: null, problems: ["route availability could not be established"], thread: null };
          if (unavailable.has(seat.key)) return { ...seat, status: "unavailable", score: null, problems: [`${route.instanceId}/${route.model} is unavailable`], thread: null };
          const left = yield* allowance(`${key}/clock`, judgeMs);
          if (left <= 0) return { ...seat, status: "limit", score: null, problems: ["the run deadline passed"], thread: null, limit: "deadline" };
          const brief = [
            `${head} ${seat.scoring ? "Scoring" : "Companion"} review, ${phase} phase.`,
            `Read your role card first: ${CARD}`,
            seat.scoring ? "" : "You are a companion: report findings and evidence; set score to null.",
            "",
            `Task: ${p.title}`,
            `Checkout: ${p.checkout} (read it; do not edit, commit or switch branches there).`,
            `Frozen candidate: ${candidate}. Comparison base: ${p.base}.`,
            `Read it with: git -C ${p.checkout} diff ${p.base}..${candidate} and git -C ${p.checkout} show ${candidate}:<path>.`,
            "",
            "Acceptance criteria:", contract.criteria, "",
            "Rubric:", contract.rubric,
            contract.checks ? `Required checks under the current contract: ${contract.checks}` : "",
            `Scale ${p.scale.min} to ${p.scale.max}, precision ${p.scale.precision}. Target ${contract.target}.`, "",
            "Permitted checks, scratch directory and evidence:", p.reviewContext, "",
            `Expected identity: ${route.label} (${route.instanceId}/${route.model}, ${route.effort.id}=${route.effort.value}), lineage ${route.lineage}.`,
            `Material code authors' lineages: ${p.codeAuthors.join(", ") || "none recorded"}.`,
            note ? `Since the last evaluation: ${note}` : "",
            priorFindings[seat.key] ? `Your own findings on the previous candidate:\n${priorFindings[seat.key]}` : "",
            "",
            "Submit with t3_submit_output: revision (the SHA you reviewed), score (null for a companion),",
            "bullets (3 to 5, how the score was reached), optional dimensions, findings (stable id, SEV1-SEV3,",
            "title, location, evidence, impact), coverageComplete (false if any required check, state or evidence",
            "could not be covered), coverageGaps (checks omitted with reasons; none if none) and",
            "model (your own model name, version and reasoning effort as you know them).",
          ].filter((line) => line !== "").join("\n");
          const ran = yield* T3.agent.try(key, {
            project: p.project,
            model: { instanceId: route.instanceId, model: route.model, options: [route.effort] },
            title: `${p.skill} ${seat.key} ${phase}: ${p.title.slice(0, 50)}`,
            brief,
            returns: Judged,
            timeout: `${left} millis`,
            runtimeMode: mode,
            interactionMode: "default",
          });
          const thread = ran.thread?.threadId ?? null;
          if (ran.outcome !== "done") return { ...seat, status: "failed", score: null, problems: [ran.reason.slice(0, 300)], thread };
          const bad = judgedProblems(p, candidate, ran.value, seat.scoring);
          // A judge whose own identity claim conflicts with its route (family, model or effort) does not count.
          const conflict = identityConflict(seat.key, ran.value.model);
          if (conflict !== null) bad.push(`identity conflict: the judge reports "${ran.value.model.slice(0, 80)}" (${conflict.join("; ")}), not ${route.label}`);
          if (bad.length > 0) return { ...seat, status: "invalid", score: null, problems: bad, thread, findings: ran.value.findings, claim: ran.value.model };
          return { ...seat, status: seat.scoring ? "scored" : "reported", score: seat.scoring ? ran.value.score : null,
            bullets: ran.value.bullets.filter((b) => b.trim()), dimensions: ran.value.dimensions, findings: ran.value.findings,
            coverageComplete: ran.value.coverageComplete, coverageGaps: ran.value.coverageGaps, claim: ran.value.model, problems: [], thread };
        });

      // Test runs: each evaluation (and each retry) takes the next row of test.scores,
      // indexed by scoring seat; a null fails that judge.
      const syntheticJudge = (seat, candidate, row, index) => {
        const score = seat.scoring ? row[index] : null;
        if (seat.scoring && (score === null || score === undefined)) {
          return { ...seat, status: "failed", score: null, problems: ["synthetic judge failure"], thread: null };
        }
        const gap = (p.test.coverageGap ?? []).includes(evalCount);
        return { ...seat, status: seat.scoring ? "scored" : "reported", score,
          bullets: [`synthetic score ${score} for ${candidate}`, "test run: no model judged this", "state-machine check only"],
          findings: [], problems: [], thread: null, coverageComplete: !gap, coverageGaps: gap ? "synthetic coverage gap" : "none" };
      };
      const syntheticRow = () => {
        const row = p.test.scores[synthetic] ?? [];
        synthetic += 1;
        return row;
      };
      const scoringIndex = (seats, seat) => seats.filter((s) => s.scoring).findIndex((s) => s.key === seat.key);

      // Host receipts for judge threads; a recorded model other than the route's invalidates the judge.
      // The same turn refreshes route availability and the spend cap before any further dispatch.
      const withReceipts = (name, judges) =>
        Effect.gen(function* () {
          const listed = judges.filter((j) => j.thread !== null && j.executed === undefined);
          if (listed.length === 0) return judges;
          const left = yield* allowance(`${name}/clock`, 10 * 60000);
          const read = left <= 0 ? { outcome: "failed", reason: "the run deadline passed" } : yield* T3.agent.try(name, {
            thread: { threadId: p.invokerThread },
            timeout: `${left} millis`,
            returns: Receipts,
            brief: [`${head} Host receipts for judge threads. Do nothing else in this turn.`,
              "For each thread, read it with t3_thread_read and report, for its run that submitted with t3_submit_output,",
              "the run ID as turnId and its executedModel, and the thread's run count as turns. Use null where the host shows nothing.",
              ...listed.map((j) => `- ${j.thread} (${j.key}, requested ${ROUTES[j.key].model})`),
              "Also call orchestrator_capabilities and report as unavailableRoutes each route key below whose provider is",
              "unavailable or lacks its exact model and effort option now:",
              ...routeList,
              capLine,
              "Submit with t3_submit_output."].join("\n"),
          });
          refresh(read.outcome === "done" ? read.value : null);
          const rows = read.outcome === "done" ? read.value.judges : [];
          return judges.map((j) => {
            if (!listed.includes(j)) return j;
            const row = rows.find((x) => x.thread === j.thread);
            const executed = { model: row?.executedModel ?? null, verified: Boolean(row?.executedModel),
              turns: row?.turns ?? null, turnId: row?.turnId ?? null, ...(read.outcome === "done" ? {} : { problem: read.reason.slice(0, 200) }) };
            if (executed.verified && String(executed.model).trim().toLowerCase() !== ROUTES[j.key].model) {
              return { ...j, executed, status: "invalid", score: null,
                problems: [...j.problems, `host executedModel ${executed.model} is not ${ROUTES[j.key].model}`] };
            }
            return { ...j, executed };
          });
        });

      // A whole evaluation of one frozen candidate, with one retry of the failed judges on the same
      // routes. A spend-cap or deadline limit is not retried.
      const evaluate = (candidate, phase, era, contract, roster, note) =>
        Effect.gen(function* () {
          evalCount += 1;
          const tag = `e${era}/eval${evalCount}`;
          const seats = seatsFor(phase, roster);
          seats.forEach(label);
          let judges;
          if (test) {
            const row = syntheticRow();
            judges = seats.map((s) => syntheticJudge(s, candidate, row, scoringIndex(seats, s)));
          } else {
            judges = yield* Effect.all(seats.map((seat, i) => judgeOnce(`${tag}/${i}`, seat, candidate, phase, contract, note)),
              { concurrency: "unbounded" });
            judges = yield* withReceipts(`${tag}/receipts`, judges);
          }
          const failed = judges.filter((j) => j.status !== "scored" && j.status !== "reported" && j.status !== "limit");
          if (failed.length > 0) {
            const again = (j, x) => ({ ...x, retried: true, retryNote: `first attempt: ${j.problems.join("; ")}` });
            if (test) {
              const row = syntheticRow();
              judges = judges.map((j) => (failed.includes(j) ? again(j, syntheticJudge(j, candidate, row, scoringIndex(seats, j))) : j));
            } else {
              judges = yield* Effect.all(judges.map((j, i) => (failed.includes(j)
                ? judgeOnce(`${tag}/${i}/retry`, { key: j.key, scoring: j.scoring, role: j.role }, candidate, phase, contract, note)
                  .pipe(Effect.map((x) => again(j, x)))
                : Effect.succeed(j))), { concurrency: "unbounded" });
              judges = yield* withReceipts(`${tag}/receipts/retry`, judges);
            }
          }
          for (const j of judges) {
            if (j.findings !== undefined) priorFindings[j.key] = findingsText([j], false);
          }
          const done = complete(judges);
          // When the evaluation finished, journaled: a result after the run deadline cannot pass.
          const endedAt = yield* now(`${tag}/ended`);
          const limit = judges.find((j) => j.status === "limit")?.limit ?? (endedAt > deadline ? "deadline" : null);
          return { judges, metric: done ? metricOf(p, judges) : null, complete: done, covered: judgesCovered(judges), late: endedAt > deadline, limit };
        });

      // ----- run state across eras -----
      const eras = [];
      const rounds = [];
      let repairsUsed = p.continuation?.repairsUsed ?? 0;
      let seq = 0;
      let floor = 0;
      let floorCandidate = p.candidate;
      let recovery = null;
      let accepted = null;
      let stopReason = null;
      let lastEval = null;
      const repairsLeft = () => roundCap === null || repairsUsed < roundCap;
      const ledgerNow = (status) => ledgerOf(p, id, status, eras, rounds, rosterLabels, prior);
      const lateStop = { stop: "run deadline passed before the evaluation finished", limit: "deadline" };
      const failStop = (ev, what) => (ev.limit === "spend-cap" ? { stop: "spend cap reached", limit: "spend-cap" }
        : ev.limit === "deadline" ? { stop: "run deadline passed", limit: "deadline" }
        : { stop: `${what} failed after its one retry` });
      const capStop = { stop: "spend cap reached", limit: "spend-cap" };
      // Every evaluation and repair, in order, for the handback and any continuation.
      const history = [];
      // The newest candidate any repair or fixing turn committed, even when it was never scored.
      let latestKnown = { candidate: p.candidate, checks: p.checks, source: "baseline", requiredFix: false };
      const known = (candidate, checks, source, requiredFix) => {
        if (candidate && candidate !== latestKnown.candidate) latestKnown = { candidate, checks, source, requiredFix };
      };

      const runEra = (index, start, contract, roster, phase0, recoveryNote) =>
        Effect.gen(function* () {
          const era = { target: contract.target, comparable: recoveryNote === null || recoveryNote.comparable,
            recovery: recoveryNote?.ledger, phase: phase0, best: null, panelEntry: null, panelEntrySeq: null,
            latest: start.candidate, latestSeq: start.seq, counter: 0, scored: [] };
          eras.push(era);
          // Score reuse is keyed by phase: a primary score never stands in for a panel score.
          const cache = new Map();
          let candidate = start.candidate;
          let checks = start.checks;
          let mySeq = start.seq;
          let roundNo = 0;
          let note = recoveryNote ? `recovery fix: ${recoveryNote.fix}` : "";
          if (era.phase === "panel") {
            era.panelEntry = candidate;
            era.panelEntrySeq = mySeq;
          }
          const record = (ev, label, rid) => {
            rounds.push(roundEntry(p, index - 1, label, rid, candidate, era.phase, ev.judges,
              ev.complete ? null : "evaluation incomplete after one retry"));
            lastEval = { candidate, judges: ev.judges, checks };
            history.push({ kind: "evaluation", round: rid, era: index, phase: era.phase, candidate, metric: ev.metric,
              judges: ev.judges.map((j) => ({ key: j.key, status: j.status, score: j.score, thread: j.thread,
                executedModel: j.executed?.model ?? null, problems: j.problems,
                findings: (j.findings ?? []).map((f) => `${f.id} ${f.severity} ${f.title}`) })) });
          };
          // Each scored entry keeps its own judges and checks, so a handback never mixes evaluations.
          const score = (ev) => {
            const entry = { candidate, metric: ev.metric, seq: mySeq, phase: era.phase, checks, covered: ev.covered, judges: ev.judges };
            cache.set(`${era.phase}:${candidate}`, entry);
            era.scored.push(entry);
          };

          // Baseline (or the recovery's or continuation's frozen baseline), always freshly evaluated.
          let ev = yield* evaluate(candidate, era.phase, index, contract, roster, note);
          record(ev, index === 1 ? (p.continuation ? "Continuation baseline" : "Baseline") : "Recovery baseline", `E${index}B0`);
          yield* pausePoint("after-baseline");
          if (!ev.complete) return failStop(ev, "evaluation");
          if (ev.late) return lateStop;
          if (capReached) return capStop;
          score(ev);
          era.best = { candidate, metric: ev.metric };
          const reviewed = { candidate, metric: ev.metric };

          for (;;) {
            // Gates first: acceptance, or panel entry.
            if (gatePasses(contract.target, ev.metric, checks, ev.covered) && mySeq >= floor) {
              if (era.phase === "primary" && roster.panel.length > 0) {
                era.phase = "panel";
                era.panelEntry = candidate;
                era.panelEntrySeq = mySeq;
                // The panel seeds its own best and counter; primary scores do not carry over.
                era.best = null;
                era.counter = 0;
                ev = yield* evaluate(candidate, "panel", index, contract, roster, "panel entry: same frozen candidate");
                record(ev, "Panel entry", `E${index}P0`);
                if (!ev.complete) return failStop(ev, "panel evaluation");
                if (ev.late) return lateStop;
                if (capReached) return capStop;
                score(ev);
                era.best = { candidate, metric: ev.metric };
                continue;
              }
              return { accepted: { candidate, metric: ev.metric, checks, judges: ev.judges } };
            }
            if (era.counter >= 2) return { stop: "two consecutive rounds without a higher score" };
            if (!repairsLeft()) return { stop: `repair-round limit of ${roundCap} reached`, limit: "rounds" };
            if (capReached) return capStop;
            // review_rounds: 1 allows one coordinator-verified repair of the first round's findings.
            const single = p.singleRound === true && index === 1 && roundNo === 0;

            // Repair from the phase's best candidate that keeps every required fix. The round counts
            // when it is dispatched, whatever its outcome.
            roundNo += 1;
            const base = eligibleBest(era.scored.filter((c) => c.phase === era.phase), floor)?.candidate ?? floorCandidate;
            let rep;
            if (test) {
              const n = repairsUsed + 1;
              const resubmit = (p.test.resubmit ?? []).includes(n);
              rep = { candidate: resubmit ? base : `test-${index}-${roundNo}`,
                checks: { passed: !(p.test.failChecks ?? []).includes(n), coverage: true, summary: "synthetic" },
                buildable: !(p.test.unbuildable ?? []).includes(n), addsRequiredFix: (p.test.requiredFix ?? []).includes(n),
                summary: "synthetic repair", dispositions: [], stop: null, unavailableRoutes: [], spendCapReached: false,
                verification: single ? { verified: !(p.test.failChecks ?? []).includes(n), summary: "synthetic verification" } : null };
              repairsUsed += 1;
            } else {
              const left = yield* allowance(`e${index}/r${roundNo}/clock`, repairMs);
              if (left <= 0) return { stop: "run deadline passed", limit: "deadline" };
              repairsUsed += 1;
              const ran = yield* T3.agent.try(`e${index}/r${roundNo}/repair`, {
                thread: { threadId: p.invokerThread },
                timeout: `${left} millis`,
                quiet: "30 minutes",
                returns: Repair,
                brief: [
                  `${head} Repair round ${roundNo} of era ${index}.`,
                  `Phase ${era.phase}. Target ${contract.target}. Best ${era.best?.metric ?? "none"} on ${era.best?.candidate ?? "none"}. Latest ${ev.metric ?? "no score"} on ${candidate}.`,
                  `Non-improving rounds: ${era.counter} of 2. Repairs used, this one included: ${repairsUsed}${roundCap === null ? "" : ` of ${roundCap}`}.`,
                  deadline === NO_DEADLINE ? "" : `Run deadline: ${new Date(deadline).toISOString()}; this turn has ${Math.floor(left / 60000)} minute(s).`,
                  p.limits?.spendCap ? `Spend cap: ${p.limits.spendCap}. If it is reached, stop with limit spend-cap.` : "",
                  "Findings from the latest evaluation:", findingsText(ev.judges, true), "",
                  `Checks on ${candidate}: ${checks.passed ? "pass" : "fail"}, coverage ${checks.coverage ? "complete" : "incomplete"}: ${checks.summary}`,
                  "",
                  contract.checks ? `Required checks under the current contract (run these and name them in checks.summary): ${contract.checks}` : "",
                  `Repair from ${base} under skills/${p.skill}/SKILL.md: decide each finding, fix the selected ones,`,
                  "keep every earlier required fix, commit the result in the checkout and run the required checks on that commit.",
                  single ? "review_rounds: 1 is adopted: repair only this round's findings, then verify every accepted repair as\n"
                    + "skills/review/references/single-round.md step 3 requires; there is no independent recheck. Report verification." : "",
                  "Update your score ledger with the score ledger below and render the score chart.",
                  "Submit with t3_submit_output: candidate (the new commit SHA), checks, buildable, addsRequiredFix (true",
                  "when later candidates must keep a fix this one adds), summary, dispositions for each finding,",
                  `verification (${single ? "{ verified, summary }" : "null"}), stop (null, or { reason, limit: none | spend-cap | deadline }`,
                  "when no repair can be made), spendCapReached, and unavailableRoutes: call orchestrator_capabilities and list",
                  "each route key below whose provider is unavailable or lacks its exact model and effort option now:",
                  ...routeList,
                  capLine,
                  "You may finish in a later turn of this thread; submit once, when the repair is committed.",
                  "",
                  "Score ledger so far:",
                  JSON.stringify(ledgerNow("in-progress")),
                ].filter((line) => line !== "").join("\n"),
              });
              if (ran.outcome !== "done") {
                refresh(null);
                return { stop: `repair step failed: ${ran.reason.slice(0, 300)}` };
              }
              rep = ran.value;
              refresh(rep);
            }
            history.push({ kind: "repair", round: `E${index}R${roundNo}`, era: index, base, candidate: rep.candidate,
              checks: rep.checks, buildable: rep.buildable, addsRequiredFix: rep.addsRequiredFix, summary: rep.summary,
              dispositions: rep.dispositions, stop: rep.stop, verification: rep.verification });
            if (rep.stop !== null) {
              known(rep.candidate, rep.checks, `repair round ${roundNo} (stopped)`, rep.addsRequiredFix);
              // A stopped repair that committed a required fix still raises the floor: nothing older is handed back.
              if (rep.addsRequiredFix && rep.candidate !== candidate) {
                seq += 1;
                floor = seq;
                floorCandidate = rep.candidate;
                era.latest = rep.candidate;
                era.latestSeq = seq;
              }
              return { stop: `repair stopped: ${rep.stop.reason}`, ...(rep.stop.limit === "none" ? {} : { limit: rep.stop.limit }) };
            }
            if (single) {
              // No recheck: the score stays bound to the reviewed candidate; verification decides.
              known(rep.candidate, rep.checks, "single-round repair", rep.addsRequiredFix);
              const v = rep.verification ?? { verified: false, summary: "no verification reported" };
              return { single: { reviewed, repaired: rep.candidate, checks: rep.checks, verified: v.verified && rep.checks.passed && rep.buildable,
                summary: v.summary } };
            }
            seq += 1;
            mySeq = seq;
            known(rep.candidate, rep.checks, `repair round ${roundNo}`, rep.addsRequiredFix);
            candidate = rep.candidate;
            checks = rep.checks;
            era.latest = candidate;
            era.latestSeq = mySeq;
            if (rep.addsRequiredFix) {
              floor = mySeq;
              floorCandidate = candidate;
            }
            note = `${rep.summary} Dispositions: ${rep.dispositions.map((d) => `${d.id} ${d.disposition}`).join(", ") || "none"}.`;

            if (!rep.buildable) {
              // Unavailable score, one non-improvement increment; no fictional zero.
              era.counter += 1;
              rounds.push({ id: `E${index}R${roundNo}`, label: `Round ${roundNo}`, candidate, era: `e${index}`, phase: era.phase,
                expected_reviewers: seatsFor(era.phase, roster).filter((s) => s.scoring).map((s) => s.key), status: "unscored",
                failure_note: `candidate could not build or run: ${rep.summary}`, scores: [] });
              ev = { judges: [], metric: null, complete: true, covered: false, late: false };
              continue;
            }
            const cached = cache.get(`${era.phase}:${candidate}`);
            if (cached !== undefined) {
              // Never re-score an evaluated candidate to shop for a higher score: reuse it, and log the round.
              ev = { judges: cached.judges, metric: cached.metric, complete: true, covered: cached.covered, late: false };
              rounds.push(roundEntry(p, index - 1, `Round ${roundNo} (resubmitted; earlier score reused)`, `E${index}R${roundNo}`,
                candidate, era.phase, cached.judges, null));
              mySeq = cached.seq;
              era.latestSeq = mySeq;
            } else {
              ev = yield* evaluate(candidate, era.phase, index, contract, roster, note);
              record(ev, `Round ${roundNo}`, `E${index}R${roundNo}`);
              if (!ev.complete) return failStop(ev, "evaluation");
              if (ev.late) return lateStop;
              if (capReached) return capStop;
              score(ev);
            }
            // Gate before progress: a gate-passing candidate advances even on a tie.
            if (gatePasses(contract.target, ev.metric, checks, ev.covered) && mySeq >= floor) continue;
            const step = progress(era, ev.metric);
            era.counter = step.counter;
            if (step.improved) era.best = { candidate, metric: ev.metric };
          }
        });

      const baseRoster = { primary, panel: panelKeys, panelPrimary: r.panelPrimary };
      const contract0 = { criteria: p.criteria, rubric: p.rubric, target: p.target, checks: null };
      const phase0 = p.skill === "hillclimb" && panelKeys.length > 0 && r.panelTrigger === "baseline" ? "panel" : "primary";
      let outcome = yield* runEra(1, { candidate: p.candidate, checks: p.checks, seq: 0 }, contract0, baseRoster, phase0, null);

      let single = null;
      if (outcome.accepted) {
        accepted = outcome.accepted;
      } else if (outcome.single) {
        // review_rounds: 1 replaces the recheck and the score gate; the recovery does not apply.
        single = outcome.single;
        stopReason = single.verified ? null : `single-round verification incomplete: ${single.summary}`;
        recovery = { outcome: "not applicable", trigger: "review_rounds: 1", diagnosis: "the adopted one-round exception replaces rechecks", fix: "none", revised: null };
      } else if (p.continuation !== undefined) {
        // An operator-approved continuation: the automatic recovery was spent by the prior run.
        stopReason = outcome.stop;
        recovery = { outcome: "spent", trigger: outcome.stop, diagnosis: `spent by prior run ${p.continuation.priorRun}`, fix: "none", revised: null };
      } else {
        stopReason = outcome.stop;
        // ----- the single automatic recovery -----
        yield* pausePoint("before-recovery");
        const committed = yield* T3.step("recovery/committed", { returns: Schema.Struct({ trigger: Schema.String, at: Schema.Number }) },
          Effect.sync(() => ({ trigger: outcome.stop, at: Date.now() })));
        const lastEra = eras[eras.length - 1];
        const capSpent = !repairsLeft();
        const failedFix = (diagnosis) => ({ outcome: "fix-failed", diagnosis, fix: "none", candidate: lastEra.latest,
          checks: { passed: false, coverage: false, summary: "not run" }, buildable: true, revised: null, unavailableRoutes: [], spendCapReached: false });
        let fix;
        let refreshed = false;
        const left = yield* allowance("recovery/clock", repairMs);
        if (outcome.limit === "deadline" || outcome.limit === "spend-cap" || left <= 0) {
          // An exhausted deadline or spend cap blocks every recovery action, setup included.
          fix = failedFix(`the ${outcome.limit === "spend-cap" ? "spend cap is" : "run deadline has"} exhausted: it blocks every recovery action`);
        } else if (test && p.test.recovery !== undefined) {
          const t = p.test.recovery;
          fix = { outcome: t.outcome, diagnosis: "synthetic", fix: "synthetic recovery",
            candidate: t.changes === false ? lastEra.latest : "test-recovery",
            checks: { passed: true, coverage: true, summary: "synthetic" }, buildable: true, unavailableRoutes: [], spendCapReached: false,
            revised: t.target === undefined ? null : { reason: "synthetic target revision", target: t.target } };
        } else {
          const ran = yield* T3.agent.try("recovery/fix", {
            thread: { threadId: p.invokerThread },
            timeout: `${left} millis`,
            quiet: "30 minutes",
            returns: Fix,
            brief: [
              `${head} The loop stopped incomplete: ${outcome.stop}.`,
              "This is the run's single automatic recovery; it has one step key and runs at most once.",
              "Follow skills/review/references/budget-exhaustion.md, 'One automatic recovery', steps 2 to 4:",
              "diagnose from the retained evidence (start no evaluator), fix the cause, and freeze the result.",
              capSpent ? `The repair-round limit (${roundCap}) is spent: a setup-only fix may recover; a candidate-changing fix is blocked, so return fix-failed if one is needed.`
                : "A fix that changes the candidate consumes one repair round, whether or not it succeeds.",
              deadline === NO_DEADLINE ? "" : `Run deadline: ${new Date(deadline).toISOString()}; this turn has ${Math.floor(left / 60000)} minute(s).`,
              p.limits?.spendCap ? `Spend cap: ${p.limits.spendCap}. If it is reached, return fix-failed.` : "",
              "Permitted changes: repair strategy, implementation, setup, rubric, target (inside the scale), required checks (describe",
              "them in revised.checks), and a roster seat",
              p.skill === "review-loop"
                ? `from the standing routes (${STATIC_ORDER.join(", ")}) that are lineage-eligible and available.`
                : `from the routes already confirmed for this run (${[...confirmed].join(", ")}), keeping the panel's size with distinct seats.`,
              "A new provider or model, a user constraint, a repository gate, a permission, publication or scope change blocks it: return fix-failed.",
              `Latest candidate: ${lastEra.latest}. Keep every required fix (latest required-fix candidate: ${floorCandidate}).`,
              "Findings from the latest evaluation:", findingsText(lastEval?.judges ?? [], true), "",
              "Submit with t3_submit_output: outcome (fixed or fix-failed), diagnosis, fix, candidate (the frozen commit to",
              "re-baseline), checks, buildable, revised (null, or the changed target, rubric, criteria, checks or roster with the",
              "reason), spendCapReached, and unavailableRoutes: re-run orchestrator_capabilities and list each route key below",
              "whose provider is unavailable or lacks its exact model and effort option now:",
              ...routeList,
              capLine,
              "You may finish in a later turn of this thread; submit once.",
              "",
              "Score ledger so far:",
              JSON.stringify(ledgerNow("in-progress")),
            ].filter((line) => line !== "").join("\n"),
          });
          fix = ran.outcome === "done" ? ran.value : failedFix(`the recovery step failed: ${ran.reason.slice(0, 300)}`);
          refreshed = ran.outcome === "done";
          const returned = yield* now("recovery/returned");
          if (fix.outcome === "fixed" && returned > deadline) fix = { ...fix, outcome: "fix-failed", diagnosis: `${fix.diagnosis} (returned after the run deadline)` };
        }
        // Text the score chart requires never arrives empty.
        fix = { ...fix, diagnosis: fix.diagnosis.trim() || "(not stated)", fix: fix.fix.trim() || "(not stated)" };
        // The fixing turn's refreshed availability and spend cap replace the older snapshot.
        if (refreshed) refresh(fix);
        else if (!test) availabilityKnown = false;
        // A candidate-changing attempt consumes a repair round, whatever its outcome; record the candidate.
        const changesCandidate = fix.candidate !== lastEra.latest;
        if (changesCandidate && !capSpent) repairsUsed += 1;
        known(fix.candidate, fix.checks, `recovery (${fix.outcome})`, false);
        // Code checks what the fix may change before any judge sees it.
        const rv = fix.revised;
        const roster = { ...baseRoster, ...(rv?.primary ? { primary: rv.primary } : {}), ...(rv?.panel ? { panel: rv.panel } : {}) };
        const swapped = rv ? [rv.primary, ...(rv.panel ?? [])].filter(Boolean) : [];
        const unauthorised = swapped.filter((k) => (p.skill === "review-loop"
          ? !ROUTES[k].standing || lineageBlocked(p, k)
          : !confirmed.has(k)) || modeOf(ROUTES[k], p.maxRuntimeMode) === null);
        // Every seat the next era would dispatch must be available now, and panel seats stay distinct.
        const nextSeats = seatsFor(eras[0].phase, roster).map((s) => s.key);
        const offSeats = nextSeats.filter((k) => unavailable.has(k));
        const panelSeats = seatsFor("panel", roster).filter((s) => s.scoring).map((s) => s.key);
        // A recovery may swap a confirmed panel seat, never add a panel or change its size.
        const panelBroken = (rv?.panel !== undefined && (p.skill !== "hillclimb" || panelKeys.length === 0))
          || (panelKeys.length > 0 && (roster.panel.length !== panelKeys.length || new Set(panelSeats).size !== panelSeats.length));
        const blocked = fix.outcome !== "fixed" ? null
          : !fix.buildable ? "the fixing turn marked its candidate unbuildable"
          : capReached ? "the spend cap is reached"
          : changesCandidate && capSpent ? "a candidate-changing fix is blocked: the repair-round limit is spent"
          : rv?.target !== undefined && !targetFits(p.scale, rv.target) ? `revised target ${rv.target} is outside the scale`
          : unauthorised.length > 0 ? `roster change to ${unauthorised.join(", ")} needs new approval`
          : offSeats.length > 0 ? `${offSeats.join(", ")} is unavailable now; declare an eligible replacement`
          : panelBroken ? "a revised panel must keep the confirmed number of distinct seats"
          : null;
        if (blocked !== null) fix = { ...fix, outcome: "fix-failed", diagnosis: `${fix.diagnosis} (${blocked})` };
        recovery = { trigger: outcome.stop, at: committed.at, outcome: fix.outcome, diagnosis: fix.diagnosis, fix: fix.fix, revised: fix.revised,
          candidate: fix.candidate };
        yield* pausePoint("after-recovery");

        if (fix.outcome === "fixed") {
          const contract = { criteria: rv?.criteria ?? contract0.criteria, rubric: rv?.rubric ?? contract0.rubric,
            target: rv?.target ?? contract0.target, checks: rv?.checks ?? contract0.checks };
          const comparable = rv === null || (rv.target === undefined && rv.rubric === undefined && rv.criteria === undefined
            && rv.checks === undefined && rv.primary === undefined && rv.panel === undefined);
          const note = {
            comparable,
            fix: `${fix.fix}${rv?.checks ? ` Required checks now: ${rv.checks}` : ""}`,
            ledger: { kind: "automatic", label: `Recovery${rv?.target !== undefined ? ` · ${p.target} → ${rv.target}` : ""}`,
              trigger: outcome.stop, diagnosis: fix.diagnosis, fix: fix.fix },
          };
          // The fix starts from the latest candidate, so it keeps every required fix and takes the next seq.
          if (changesCandidate) seq += 1;
          // Retain the phase: primary stays primary; panel stays panel.
          outcome = yield* runEra(2, { candidate: fix.candidate, checks: fix.checks, seq }, contract, roster, eras[0].phase, note);
          if (outcome.accepted) {
            accepted = outcome.accepted;
            stopReason = null;
          } else {
            stopReason = `${stopReason}; after the recovery: ${outcome.stop}`;
          }
        }
      }

      // ----- hand back -----
      const revisedPass = accepted !== null && eras.length > 1 && !eras[1].comparable;
      const status = accepted !== null ? (revisedPass ? "passed-revised" : "passed")
        : single?.verified ? "passed" : "goal-not-met";
      const reviewedEntry = single ? eras[0].scored.find((c) => c.candidate === single.reviewed.candidate) : null;
      const final = accepted !== null
        ? { candidate: accepted.candidate, metric: accepted.metric, note: "accepted candidate", entry: { judges: accepted.judges, checks: accepted.checks } }
        : single
          ? { candidate: single.repaired, metric: null, entry: { judges: reviewedEntry?.judges ?? [], checks: single.checks },
            note: `${single.verified ? "fixes coordinator-verified, not independently re-reviewed" : "repairs not verified"}; `
              + `the score ${single.reviewed.metric} stays bound to the reviewed candidate ${single.reviewed.candidate}` }
          : finalCandidate(eras, floor, floorCandidate);
      const finalJudges = final.entry?.judges ?? [];
      const ledger = ledgerNow(status);
      const selectionOut = selection ?? { order: [primary], basis: "named roster", gates: [] };
      const result = {
        run: id, test, skill: p.skill, status,
        final: { candidate: final.candidate, metric: final.metric, note: final.note, checks: final.entry?.checks ?? null },
        stopReason, recovery, repairsUsed, requiredFixFloor: floorCandidate, latestKnown, single, history,
        continuation: p.continuation ? { priorRun: p.continuation.priorRun, repairsUsed: p.continuation.repairsUsed, approval: p.continuation.approval } : null,
        selection: selectionOut,
        eras: eras.map((e) => ({ target: e.target, comparable: e.comparable, phase: e.phase, best: e.best, panelEntry: e.panelEntry, counter: e.counter })),
        ledger,
      };
      yield* tell("callback", [
        test ? "TEST RUN with synthetic scores. Report this result only." : "",
        `Result: ${status}${revisedPass ? ` (revised target ${eras[1].target}; the original target ${p.target} was not met)` : ""}`,
        `Final candidate: ${final.candidate} (${final.metric ?? "no score"}; ${final.note})`,
        final.entry?.checks ? `Checks on the final candidate: ${final.entry.checks.passed ? "pass" : "fail"}, coverage ${final.entry.checks.coverage ? "complete" : "incomplete"}: ${final.entry.checks.summary}` : "",
        latestKnown.candidate !== final.candidate
          ? `Latest known candidate: ${latestKnown.candidate} from ${latestKnown.source}${latestKnown.requiredFix ? ", adds a required fix" : ""}; checks ${latestKnown.checks?.passed ? "pass" : "fail or not run"}: ${latestKnown.checks?.summary ?? "none"}. It has no complete score.`
          : "",
        stopReason ? `Stop: ${stopReason}` : "",
        recovery
          ? `Recovery: ${recovery.outcome} after "${recovery.trigger}" — ${recovery.diagnosis}${recovery.revised ? ` Revised: ${JSON.stringify(recovery.revised)}` : ""}`
          : "Recovery: not used",
        `Reviewer selection: ${selectionOut.basis}${selectionOut.gates.length ? `; gates: ${selectionOut.gates.join("; ")}` : ""}`,
        `Repairs used: ${repairsUsed}${roundCap === null ? "" : ` of ${roundCap}`}${p.continuation ? ` (including ${p.continuation.repairsUsed} from run ${p.continuation.priorRun})` : ""}.`,
        deadline !== NO_DEADLINE && status === "goal-not-met" && /deadline/.test(stopReason ?? "") ? "The run deadline has passed: do no further work under it." : "",
        `Findings on the final candidate ${final.candidate}:`, finalJudges.length ? findingsText(finalJudges, true) : "- no complete evaluation of this candidate",
        "Judge receipts for the final candidate:", receiptsText(finalJudges),
        lastEval && lastEval.candidate !== final.candidate ? `Latest evaluated candidate ${lastEval.candidate} findings (a different revision):\n${findingsText(lastEval.judges, false)}` : "",
        "Attempt history (evaluations and repairs, in order):",
        ...history.map((h) => (h.kind === "evaluation"
          ? `- ${h.round} ${h.phase} eval of ${h.candidate}: ${h.metric ?? "no score"}; `
            + h.judges.map((j) => `${j.key} ${j.status}${j.score === null || j.score === undefined ? "" : ` ${j.score}`} (${j.executedModel ?? "model unverified"}; ${j.findings.join(", ") || "no findings"})`).join("; ")
          : `- ${h.round} repair from ${h.base} to ${h.candidate}: ${h.stop ? `stopped (${h.stop.reason})` : h.summary.slice(0, 200)}; `
            + `checks ${h.checks.passed ? "pass" : "fail"}${h.addsRequiredFix ? "; adds a required fix" : ""}; `
            + `dispositions ${h.dispositions.map((d) => `${d.id} ${d.disposition}: ${d.note.slice(0, 120)}`).join(" | ") || "none"}`
            + (h.verification ? `; verification ${h.verification.verified ? "passed" : "failed"}: ${h.verification.summary.slice(0, 200)}` : ""))),
        "",
        test ? "" : `Continue with skills/${p.skill}/SKILL.md from its delivery step, using this result. Write the ledger below to your score ledger and render the chart.`,
        "Score ledger:",
        JSON.stringify(ledger),
      ].filter((line) => line !== "").join("\n"));
      return result;
    }),
);
