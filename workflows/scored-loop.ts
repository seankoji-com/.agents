// @tested-t3 0.1.12-nightly.20261123.5151
// @start manual
//
// Durable bookkeeping for skills/review-loop/SKILL.md: reviewer selection, the
// frozen candidate, the score, the target, check and coverage gate, the
// two-non-improving-rounds stop, one retry of a failed evaluation, explicit
// limits, required-fix eligibility, the single automatic recovery and the score
// ledger. Judgment stays in agent steps: the judge scores in a fresh thread; the
// invoking thread repairs, reports receipts and limits, and diagnoses the recovery.
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
// continuation packet carries the spent slot, so no run family gets two.

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
};
const ROUTE_KEYS = Object.keys(ROUTES);
const STATIC_ORDER = ["sol", "opus", "sonnet-agy", "neon", "hydrogen"];
const LINEAGES = ["anthropic", "openai", "google", "deepseek", "xai", "qwen", "other"];
const SEVERITIES = ["SEV1", "SEV2", "SEV3"];
const CARD = `${process.env.HOME}/.agents/skills/review/references/assigned-reviewer.md`;
const NO_DEADLINE = Number.POSITIVE_INFINITY;

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
};
const EFFORT_WORDS = ["minimal", "low", "medium", "high", "xhigh", "max", "ultra", "ultrathink"];

// ---------- schemas ----------

const Checks = Schema.Struct({ passed: Schema.Boolean, coverage: Schema.Boolean, summary: Schema.String });
const Route = Schema.Literals(ROUTE_KEYS);

const Test = Schema.Struct({
  // One row per evaluation and per retry, in order: the primary's score, or null for a failure.
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

const Packet = Schema.Struct({
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
  scale: Schema.Struct({ min: Schema.Number, max: Schema.Number, precision: Schema.Number }),
  // Model families that materially wrote the code, repairers included.
  codeAuthors: Schema.Array(Schema.Literals(LINEAGES)),
  // Permitted checks, commands, scratch directory and evidence requirements for the judge.
  reviewContext: Schema.String,
  // Only when the user named the primary reviewer; otherwise the workflow selects it.
  primary: Schema.optional(Route),
  // Finding-only companions, such as Hydrogen for visual scope.
  companions: Schema.optional(Schema.Array(Route)),
  limits: Schema.optional(Schema.Struct({
    repairRounds: Schema.optional(Schema.Number),
    deadline: Schema.optional(Schema.String),
    // As the operator stated it; the invoking thread reports reaching it.
    spendCap: Schema.optional(Schema.String),
  })),
  // An operator-approved continuation of a stopped run: its automatic recovery is spent.
  continuation: Schema.optional(Schema.Struct({ priorRun: Schema.String, repairsUsed: Schema.Number, approval: Schema.String })),
  // The project adopted `review_rounds: 1` (skills/review/references/single-round.md).
  singleRound: Schema.optional(Schema.Boolean),
  judgeMinutes: Schema.optional(Schema.Number),
  repairMinutes: Schema.optional(Schema.Number),
  test: Schema.optional(Test),
});
const decodePacket = Schema.decodeUnknownSync(Packet);

// Every invoker turn reports, from orchestrator_capabilities, the routes it verified as available
// (exact model and effort option), and whether the spend cap is reached.
const Report = {
  availableRoutes: Schema.Array(Schema.String),
  spendCapReached: Schema.Boolean,
};
const Pace = Schema.Struct({
  ...Report,
  observedAt: Schema.String,
  providers: Schema.Array(Schema.Struct({
    provider: Schema.String,
    paceScore: Schema.NullOr(Schema.Number),
    paceBasis: Schema.NullOr(Schema.String),
  })),
});
const Receipts = Schema.Struct({
  ...Report,
  judges: Schema.Array(Schema.Struct({
    thread: Schema.String,
    turnId: Schema.NullOr(Schema.String),
    executedModel: Schema.NullOr(Schema.String),
    turns: Schema.NullOr(Schema.Number),
  })),
});
const Finding = Schema.Struct({
  id: Schema.String,
  severity: Schema.Literals(SEVERITIES),
  title: Schema.String,
  location: Schema.String,
  evidence: Schema.String,
  impact: Schema.String,
});
const Judged = Schema.Struct({
  revision: Schema.String,
  score: Schema.NullOr(Schema.Number),
  bullets: Schema.Array(Schema.String),
  dimensions: Schema.optional(Schema.Array(Schema.Struct({ name: Schema.String, score: Schema.Number, weight: Schema.optional(Schema.Number) }))),
  findings: Schema.Array(Finding),
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
});
const Fix = Schema.Struct({
  ...Report,
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
    checks: Schema.optional(Schema.String),
    primary: Schema.optional(Route),
  })),
});

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

function lineageBlocked(p, key) {
  return p.scope === "code" && p.codeAuthors.includes(ROUTES[key].lineage);
}

function targetFits(scale, target) {
  return typeof target === "number" && target > scale.min && target <= scale.max;
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
  if (p.primary !== undefined && lineageBlocked(p, p.primary)) {
    problems.push(`${p.primary} shares the ${ROUTES[p.primary].lineage} lineage with a code author; name an eligible reviewer`);
  }
  for (const key of [p.primary, ...(p.companions ?? [])].filter(Boolean)) {
    if (modeOf(ROUTES[key], p.maxRuntimeMode) === null) problems.push(`${key} needs ${ROUTES[key].minMode}, above the invoker's ${p.maxRuntimeMode}`);
  }
  if (p.primary !== undefined && (p.companions ?? []).includes(p.primary)) problems.push("the primary cannot also be a companion");
  const lim = p.limits ?? {};
  if (lim.repairRounds !== undefined && !(Number.isInteger(lim.repairRounds) && lim.repairRounds >= 0)) problems.push("limits.repairRounds must be a whole number");
  if (lim.deadline !== undefined && !Number.isFinite(Date.parse(lim.deadline))) problems.push("limits.deadline must be an ISO 8601 time");
  const c = p.continuation;
  if (c !== undefined) {
    if (!c.priorRun.trim() || !c.approval.trim()) problems.push("continuation needs priorRun and the operator's approval");
    if (!(Number.isInteger(c.repairsUsed) && c.repairsUsed >= 0)) problems.push("continuation.repairsUsed must be a whole number");
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
    .map((key) => ({ key, pace: pace?.providers.find((x) => x.provider === ROUTES[key].instanceId) }))
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
  if (others.length > 0 && !FAMILY_WORDS[route.lineage].some(has)) conflicts.push(`names ${others.join(", ")}`);
  const siblings = (SIBLINGS[key] ?? []).filter(has);
  if (siblings.length > 0) conflicts.push(`names ${siblings.join(", ")}`);
  const efforts = EFFORT_WORDS.filter((w) => w !== route.effort.value && has(w));
  if (efforts.length > 0) conflicts.push(`reports effort ${efforts.join(", ")}`);
  const versions = [...text.matchAll(new RegExp(`(?:${FAMILY_WORDS[route.lineage].join("|")})[\\s-]*v?(\\d+(?:\\.\\d+)?)`, "g"))].map((m) => m[1]);
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

// The candidate an incomplete stop hands back: the best eligible scored candidate across eras
// when the contract never changed, else the current era's; else the required-fix candidate or
// the latest work, unscored.
function finalCandidate(eras, floor, latest) {
  const last = eras[eras.length - 1];
  const comparable = eras.every((e) => e.comparable);
  const best = eligibleBest((comparable ? eras : [last]).flatMap((e) => e.scored), floor);
  if (best !== null) {
    return { candidate: best.candidate, metric: best.metric, entry: best,
      note: comparable ? "best fully scored candidate that keeps required fixes" : "best under the current contract; earlier scores historical" };
  }
  return { candidate: latest.candidate, metric: null, entry: null, note: `no ranked best; latest eligible work from ${latest.source}, unscored` };
}

function ledgerOf(p, runId, status, eras, rounds, reviewers) {
  return {
    version: 1,
    // The ledger's precision is decimal places; the packet's is the rubric's step.
    run: { title: p.title, id: runId, skill: "review-loop", status, scale: { min: p.scale.min, max: p.scale.max, precision: decimals(p.scale.precision) } },
    reviewers: reviewers.length ? reviewers : [{ id: "none", label: "no judge" }],
    eras: eras.map((e, i) => ({
      id: `e${i + 1}`,
      label: i === 0 ? (p.continuation ? `Continuation of ${p.continuation.priorRun}` : "Original contract") : "Recovery era",
      target: e.target,
      ...(e.target !== p.target ? { original_target: p.target } : {}),
      historical: i < eras.length - 1 && !eras[i + 1].comparable,
      comparable_to_prev: i === 0 ? true : e.comparable,
      ...(e.recovery ? { recovery: e.recovery } : {}),
    })),
    rounds: rounds.length ? rounds : [{ id: "B0", label: "Baseline", era: "e1", phase: "primary",
      expected_reviewers: [reviewers[0]?.id ?? "none"], status: "unscored", failure_note: "no evaluation completed", scores: [] }],
  };
}

function roundEntry(p, era, label, id, candidate, judges, failure) {
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
  return { id, label, candidate, era: `e${era}`, phase: "primary", expected_reviewers: judges.filter((j) => j.scoring).map((j) => j.key),
    status, ...(status === "scored" ? {} : { failure_note: failure ?? "the judge returned no score" }), scores };
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
    + `requested ${ROUTES[j.key].model} ${ROUTES[j.key].effort.id}=${ROUTES[j.key].effort.value}, executedModel `
    + `${j.executed?.model ?? "null"} (${j.executed?.verified ? "verified" : "unverified"}), effort unverified (the host records none), `
    + `self-reported "${String(j.claim ?? "").slice(0, 80)}"`).join("\n") || "- none";
}

// ---------- workflow ----------

export default T3.workflow(
  "scored-loop",
  { version: 6, payload: T3.WebhookRequest, triggers: [T3.webhook("start")] },
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
      const p = parsed.value;
      const test = p.test !== undefined;
      yield* T3.title(`${test ? "[test] " : ""}review-loop: ${p.title.slice(0, 80)}`);
      const head = `[T3 workflow scored-loop (review-loop), run ${id}]`;
      const tell = (name, lines) => T3.agent(name, { thread: { threadId: p.invokerThread }, brief: [head, ...lines].filter((l) => l !== "").join("\n") });
      const problems = packetProblems(p);
      if (problems.length > 0) {
        yield* tell("callback", ["Packet rejected; no judge was dispatched.", ...problems.map((x) => `- ${x}`),
          "Fix the packet and start again with a new idempotency key."]);
        return { run: id, outcome: "rejected", problems };
      }

      // ----- limits: one guard, journaled, before each dispatch and after each invoker result -----
      const deadline = p.limits?.deadline !== undefined ? Date.parse(p.limits.deadline) : NO_DEADLINE;
      const roundCap = p.limits?.repairRounds ?? null;
      const judgeMs = Math.round((p.judgeMinutes ?? 60) * 60000);
      const repairMs = Math.round((p.repairMinutes ?? 240) * 60000);
      const routeList = ROUTE_KEYS.map((k) => `- ${k}: ${ROUTES[k].instanceId}/${ROUTES[k].model} with ${ROUTES[k].effort.id}=${ROUTES[k].effort.value}`);
      const reportAsk = [
        "Also call orchestrator_capabilities and report as availableRoutes each route key below whose provider lists",
        "its exact model with that effort option now (leave out any you could not confirm):",
        ...routeList,
        p.limits?.spendCap ? `Report spendCapReached true if this spend cap is reached: ${p.limits.spendCap}.` : "Report spendCapReached false.",
      ];
      // The latest invoker report. `available` is null when the last report failed: no judge dispatches then.
      let available = test ? new Set(ROUTE_KEYS) : null;
      let capReached = false;
      const report = (value) => {
        if (value === null) {
          if (!test) available = null;
          return;
        }
        available = new Set(value.availableRoutes.filter((k) => ROUTE_KEYS.includes(k)));
        capReached = capReached || value.spendCapReached === true;
      };
      // Journaled, so a replay repeats the decision the original run made. Time left is measured live
      // the first time; a result observed after the deadline is caught by the same guard afterwards.
      const limits = (name, wanted) => T3.step(name, { returns: Schema.Struct({ left: Schema.Number, stop: Schema.NullOr(Schema.String) }) },
        Effect.sync(() => {
          const left = deadline === NO_DEADLINE ? wanted : Math.min(wanted, deadline - Date.now());
          return { left, stop: capReached ? "spend-cap" : left <= 0 ? "deadline" : null };
        }));
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
      let pace = null;
      let selectionProblem = test ? "test run: static order" : null;
      if (!test) {
        const g = yield* limits("select/limits", 10 * 60000);
        const paced = g.stop !== null ? { outcome: "failed", reason: limitStop(g.stop).stop } : yield* T3.agent.try("select", {
          thread: { threadId: p.invokerThread },
          timeout: `${g.left} millis`,
          returns: Pace,
          brief: [`${head} Reviewer selection data. Do nothing else in this turn.`,
            "Call the limits MCP tool limits-limits_snapshot with detail \"brief\". For each provider instance codex, claudeAgent",
            "and antigravity, report its paceScore and paceBasis (null when the snapshot has none) and the observation time as observedAt.",
            ...reportAsk, "Submit with t3_submit_output."].join("\n"),
        });
        if (paced.outcome === "done") {
          pace = paced.value;
          report(pace);
        } else {
          selectionProblem = paced.reason.slice(0, 200);
        }
      }
      if (capReached) {
        yield* tell("callback", [`Spend cap reached before any judge was dispatched: ${p.limits?.spendCap ?? "as reported"}. Nothing was scored.`]);
        return { run: id, outcome: "blocked", problems: ["spend cap reached"] };
      }
      if (available === null) {
        yield* tell("callback", [`Route availability could not be established, so no judge was dispatched: ${selectionProblem}.`,
          "Start again with a new idempotency key when the invoking thread can answer the selection turn."]);
        return { run: id, outcome: "blocked", problems: ["route availability unknown"] };
      }
      let selection;
      let primary = p.primary ?? null;
      if (primary !== null) {
        selection = { order: [primary], basis: "named by the user", gates: available.has(primary) ? [] : [`${primary}: not reported available`] };
        if (!available.has(primary)) primary = null;
      } else {
        selection = selectPrimary(p, pace, available);
        if (selectionProblem) selection.basis += ` (${selectionProblem})`;
        primary = selection.order[0] ?? null;
      }
      const offCompanions = (p.companions ?? []).filter((k) => !available.has(k));
      if (primary === null || offCompanions.length > 0) {
        yield* tell("callback", ["No eligible, available reviewer for this roster: hold dependent review for the operator's choice.",
          ...selection.gates.map((g) => `- ${g}`), ...offCompanions.map((k) => `- companion ${k}: not reported available`)]);
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
            const score = seat.scoring ? p.test.scores[synthetic++] : null;
            if (seat.scoring && (score === null || score === undefined)) return { ...seat, status: "failed", score: null, problems: ["synthetic judge failure"], thread: null };
            const gap = (p.test.coverageGap ?? []).includes(evalCount);
            return { ...seat, status: seat.scoring ? "scored" : "reported", score, problems: [], thread: null, findings: [],
              bullets: [`synthetic score ${score} for ${candidate}`, "test run: no model judged this", "state-machine check only"],
              coverageComplete: !gap, coverageGaps: gap ? "synthetic coverage gap" : "none", claim: "synthetic" };
          }
          const ran = yield* T3.agent.try(key, {
            project: p.project,
            model: { instanceId: route.instanceId, model: route.model, options: [route.effort] },
            title: `review-loop ${seat.key}: ${p.title.slice(0, 50)}`,
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
              `Scale ${p.scale.min} to ${p.scale.max}, precision ${p.scale.precision}. Target ${contract.target}.`, "",
              "Permitted checks, scratch directory and evidence:", p.reviewContext, "",
              `Expected identity: ${route.label} (${route.instanceId}/${route.model}, ${route.effort.id}=${route.effort.value}), lineage ${route.lineage}.`,
              `Material code authors' lineages: ${p.codeAuthors.join(", ") || "none recorded"}.`,
              note ? `Since the last evaluation: ${note}` : "",
              priorFindings[seat.key] ? `Your own findings on the previous candidate:\n${priorFindings[seat.key]}` : "",
              "", "Submit with t3_submit_output: revision (the SHA you reviewed), score (null for a companion), bullets (3 to 5,",
              "how the score was reached), optional dimensions, findings (stable id, SEV1-SEV3, title, location, evidence, impact),",
              "coverageComplete (false if any required check, state or evidence could not be covered), coverageGaps, and model",
              "(your own model name, version and reasoning effort as you know them).",
            ].filter((l) => l !== "").join("\n"),
          });
          const thread = ran.thread?.threadId ?? null;
          if (ran.outcome !== "done") return { ...seat, status: "failed", score: null, problems: [ran.reason.slice(0, 300)], thread };
          const bad = judgedProblems(p, seat.key, candidate, ran.value, seat.scoring);
          const base = { ...seat, thread, findings: ran.value.findings, claim: ran.value.model, coverageComplete: ran.value.coverageComplete,
            coverageGaps: ran.value.coverageGaps, bullets: ran.value.bullets.filter((b) => b.trim()), dimensions: ran.value.dimensions };
          if (bad.length > 0) return { ...base, status: "invalid", score: null, problems: bad };
          return { ...base, status: seat.scoring ? "scored" : "reported", score: seat.scoring ? ran.value.score : null, problems: [] };
        });

      // Host receipts for judge threads, with a refreshed limits report; a recorded model other than the
      // route's invalidates the judge.
      const withReceipts = (name, judges) =>
        Effect.gen(function* () {
          const listed = judges.filter((j) => j.thread !== null && j.executed === undefined);
          if (listed.length === 0) return judges;
          const g = yield* limits(`${name}/limits`, 10 * 60000);
          const read = g.stop !== null ? { outcome: "failed", reason: limitStop(g.stop).stop } : yield* T3.agent.try(name, {
            thread: { threadId: p.invokerThread },
            timeout: `${g.left} millis`,
            returns: Receipts,
            brief: [`${head} Host receipts for judge threads. Do nothing else in this turn.`,
              "For each thread, read it with t3_thread_read and report, for its run that submitted with t3_submit_output, the run ID",
              "as turnId and its executedModel, and the thread's run count as turns. Use null where the host shows nothing.",
              ...listed.map((j) => `- ${j.thread} (${j.key}, requested ${ROUTES[j.key].model})`), ...reportAsk,
              "Submit with t3_submit_output."].join("\n"),
          });
          report(read.outcome === "done" ? read.value : null);
          const rows = read.outcome === "done" ? read.value.judges : [];
          return judges.map((j) => {
            if (!listed.includes(j)) return j;
            const row = rows.find((x) => x.thread === j.thread);
            const executed = { model: row?.executedModel ?? null, verified: Boolean(row?.executedModel), turns: row?.turns ?? null,
              turnId: row?.turnId ?? null, ...(read.outcome === "done" ? {} : { problem: read.reason.slice(0, 200) }) };
            if (executed.verified && String(executed.model).trim().toLowerCase() !== ROUTES[j.key].model) {
              return { ...j, executed, status: "invalid", score: null, problems: [...j.problems, `host executedModel ${executed.model} is not ${ROUTES[j.key].model}`] };
            }
            return { ...j, executed };
          });
        });

      const history = [];
      const snapshot = (j) => ({ key: j.key, status: j.status, score: j.score, thread: j.thread, executedModel: j.executed?.model ?? null,
        problems: j.problems, coverageGaps: j.coverageComplete === false ? j.coverageGaps : null,
        findings: (j.findings ?? []).map((f) => ({ id: f.id, severity: f.severity, title: f.title, location: f.location, evidence: f.evidence.slice(0, 400) })) });

      // One evaluation of a frozen candidate, with one retry of failed judges on the same routes.
      // Limit stops are not retried. Every attempt, first tries included, enters the history.
      const evaluate = (candidate, era, contract, note, rid) =>
        Effect.gen(function* () {
          evalCount += 1;
          const tag = `e${era}/eval${evalCount}`;
          const seats = [{ key: primary, scoring: true, role: "Primary" }, ...(p.companions ?? []).map((key) => ({ key, scoring: false, role: "Companion" }))];
          seats.forEach((s) => label(s.key, s.role));
          let judges = yield* Effect.all(seats.map((seat, i) => judgeOnce(`${tag}/${i}`, seat, candidate, contract, note)), { concurrency: "unbounded" });
          judges = yield* withReceipts(`${tag}/receipts`, judges);
          history.push({ kind: "evaluation", round: rid, attempt: "first", era, candidate, judges: judges.map(snapshot) });
          const failed = judges.filter((j) => j.status !== "scored" && j.status !== "reported" && j.status !== "limit");
          if (failed.length > 0) {
            judges = yield* Effect.all(judges.map((j, i) => (failed.includes(j)
              ? judgeOnce(`${tag}/${i}/retry`, { key: j.key, scoring: j.scoring, role: j.role }, candidate, contract, note)
                .pipe(Effect.map((x) => ({ ...x, retried: true, retryNote: `first attempt: ${j.problems.join("; ")}` })))
              : Effect.succeed(j))), { concurrency: "unbounded" });
            judges = yield* withReceipts(`${tag}/receipts/retry`, judges);
            history.push({ kind: "evaluation", round: rid, attempt: "retry", era, candidate, judges: judges.map(snapshot) });
          }
          for (const j of judges) {
            if (j.findings !== undefined) priorFindings[j.key] = findingsText([j], false);
          }
          const g = yield* limits(`${tag}/after`, 1);
          const done = judges.every((j) => j.status === "scored" || j.status === "reported");
          const primaryJudge = judges.find((j) => j.scoring);
          return { judges, complete: done, covered: judges.every((j) => j.coverageComplete !== false),
            metric: done && typeof primaryJudge?.score === "number" ? quantise(primaryJudge.score, p.scale) : null,
            limit: g.stop ?? judges.find((j) => j.status === "limit")?.limit ?? null };
        });

      // ----- run state -----
      const eras = [];
      const rounds = [];
      let repairsUsed = p.continuation?.repairsUsed ?? 0;
      let seq = 0;
      let floor = 0;
      let latest = { candidate: p.candidate, checks: p.checks, seq: 0, source: "the baseline", requiredFix: false };
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
        if (requiredFix) floor = Math.max(floor, latest.seq);
        return latest;
      };

      const runEra = (index, start, contract, recoveryNote) =>
        Effect.gen(function* () {
          const era = { target: contract.target, comparable: recoveryNote === null || recoveryNote.comparable, recovery: recoveryNote?.ledger,
            best: null, counter: 0, scored: [] };
          eras.push(era);
          const cache = new Map();
          let at = start;
          let roundNo = 0;
          let note = recoveryNote ? `recovery fix: ${recoveryNote.fix}` : "";
          const judgeRound = (labelText, rid) =>
            Effect.gen(function* () {
              const ev = yield* evaluate(at.candidate, index, contract, note, rid);
              rounds.push(roundEntry(p, index, labelText, rid, at.candidate, ev.judges, ev.complete ? null : "evaluation incomplete after one retry"));
              lastEval = { candidate: at.candidate, judges: ev.judges };
              if (ev.complete && ev.limit === null) {
                const entry = { candidate: at.candidate, metric: ev.metric, seq: at.seq, checks: at.checks, covered: ev.covered, judges: ev.judges };
                cache.set(at.candidate, entry);
                era.scored.push(entry);
              }
              return ev;
            });

          let ev = yield* judgeRound(index === 1 ? (p.continuation ? "Continuation baseline" : "Baseline") : "Recovery baseline", `E${index}B0`);
          yield* pausePoint("after-baseline");
          if (ev.limit !== null) return limitStop(ev.limit);
          if (!ev.complete) return { stop: "evaluation failed after its one retry" };
          era.best = { candidate: at.candidate, metric: ev.metric };
          const reviewed = { candidate: at.candidate, metric: ev.metric, covered: ev.covered };

          for (;;) {
            if (gatePasses(contract.target, ev.metric, at.checks, ev.covered) && at.seq >= floor) {
              return { accepted: { candidate: at.candidate, metric: ev.metric, checks: at.checks, judges: ev.judges } };
            }
            if (era.counter >= 2) return { stop: "two consecutive rounds without a higher score" };
            if (!repairsLeft()) return { stop: `repair-round limit of ${roundCap} reached`, limit: "rounds" };
            // review_rounds: 1 allows one scored review (whichever era completes it) and one verified repair.
            const single = p.singleRound === true && roundNo === 0;
            if (single && !reviewed.covered) return { stop: "single round: the review reported a coverage gap, so the one-round exception does not apply", single: "not-applicable" };

            roundNo += 1;
            const rid = `E${index}R${roundNo}`;
            const base = eligibleBest(era.scored, floor)?.candidate ?? latest.candidate;
            const g = yield* limits(`${rid}/limits`, repairMs);
            if (g.stop !== null) return limitStop(g.stop);
            repairsUsed += 1;
            let rep;
            if (test) {
              const n = repairsUsed;
              rep = { candidate: (p.test.resubmit ?? []).includes(n) ? base : `test-${index}-${roundNo}`,
                checks: { passed: !(p.test.failChecks ?? []).includes(n), coverage: true, summary: "synthetic" },
                buildable: !(p.test.unbuildable ?? []).includes(n), addsRequiredFix: (p.test.requiredFix ?? []).includes(n),
                summary: "synthetic repair", dispositions: [], stop: null, availableRoutes: ROUTE_KEYS,
                spendCapReached: p.test.capAfterRepair === n,
                verification: single ? { verified: !(p.test.failChecks ?? []).includes(n), summary: "synthetic verification" } : null };
            } else {
              const ran = yield* T3.agent.try(`${rid}/repair`, {
                thread: { threadId: p.invokerThread },
                timeout: `${g.left} millis`,
                quiet: "30 minutes",
                returns: Repair,
                brief: [
                  `${head} Repair round ${roundNo} of era ${index}.`,
                  `Target ${contract.target}. Best ${era.best?.metric ?? "none"} on ${era.best?.candidate ?? "none"}. Latest ${ev.metric ?? "no score"} on ${at.candidate}.`,
                  `Non-improving rounds: ${era.counter} of 2. Repairs used, this one included: ${repairsUsed}${roundCap === null ? "" : ` of ${roundCap}`}.`,
                  deadline === NO_DEADLINE ? "" : `Run deadline: ${new Date(deadline).toISOString()}; this turn has ${Math.floor(g.left / 60000)} minute(s).`,
                  "Findings from the latest evaluation:", findingsText(ev.judges, true), "",
                  `Checks on ${at.candidate}: ${at.checks.passed ? "pass" : "fail"}, coverage ${at.checks.coverage ? "complete" : "incomplete"}: ${at.checks.summary}`,
                  contract.checks ? `Required checks under the current contract (run these and name them in checks.summary): ${contract.checks}` : "",
                  "", `Repair from ${base} under skills/review-loop/SKILL.md: decide each finding, fix the selected ones, keep every`,
                  "earlier required fix, commit the result in the checkout and run the required checks on that commit.",
                  single ? "review_rounds: 1 is adopted: repair only this round's findings, then verify every accepted repair as\nskills/review/references/single-round.md step 3 requires; there is no recheck. Report verification." : "",
                  "Update your score ledger with the score ledger below and render the score chart.",
                  "Submit with t3_submit_output: candidate (the new commit SHA), checks, buildable, addsRequiredFix (true when later",
                  "candidates must keep a fix this one adds), summary, dispositions for each finding with a note,",
                  `verification (${single ? "{ verified, summary }" : "null"}), and stop (null, or { reason, limit: none | spend-cap | deadline }).`,
                  ...reportAsk,
                  "You may finish in a later turn of this thread; submit once, when the repair is committed.",
                  "", "Score ledger so far:", JSON.stringify(ledgerNow("in-progress")),
                ].filter((l) => l !== "").join("\n"),
              });
              if (ran.outcome !== "done") {
                report(null);
                return { stop: `repair step failed: ${ran.reason.slice(0, 300)}` };
              }
              rep = ran.value;
            }
            report(rep);
            const now = commit(rep.candidate, rep.checks, `repair ${rid}${rep.stop ? " (stopped)" : ""}`, rep.addsRequiredFix);
            history.push({ kind: "repair", round: rid, era: index, base, candidate: rep.candidate, checks: rep.checks, buildable: rep.buildable,
              addsRequiredFix: rep.addsRequiredFix, summary: rep.summary, dispositions: rep.dispositions, stop: rep.stop, verification: rep.verification });
            if (rep.stop !== null) return { stop: `repair stopped: ${rep.stop.reason}`, ...(rep.stop.limit === "none" ? {} : { limit: rep.stop.limit }) };
            const after = yield* limits(`${rid}/after`, 1);
            if (after.stop !== null) return limitStop(after.stop);
            if (single) {
              const verified = rep.verification?.verified === true && rep.checks.passed && rep.buildable;
              return { single: verified ? "verified" : "unverified", reviewed, repaired: now, verification: rep.verification?.summary ?? "no verification reported" };
            }
            at = now;
            note = `${rep.summary} Dispositions: ${rep.dispositions.map((d) => `${d.id} ${d.disposition}`).join(", ") || "none"}.`;
            if (!rep.buildable) {
              // Unavailable score, one non-improvement increment; no fictional zero.
              era.counter += 1;
              rounds.push({ id: rid, label: `Round ${roundNo}`, candidate: at.candidate, era: `e${index}`, phase: "primary",
                expected_reviewers: [primary], status: "unscored", failure_note: `candidate could not build or run: ${rep.summary}`, scores: [] });
              ev = { judges: [], metric: null, complete: true, covered: false, limit: null };
              continue;
            }
            const cached = cache.get(at.candidate);
            if (cached !== undefined) {
              // Never re-score an evaluated candidate to shop for a higher score: reuse it, and log the round.
              at = { ...at, seq: cached.seq };
              ev = { judges: cached.judges, metric: cached.metric, complete: true, covered: cached.covered, limit: null };
              rounds.push(roundEntry(p, index, `Round ${roundNo} (resubmitted; earlier score reused)`, rid, at.candidate, cached.judges, null));
            } else {
              ev = yield* judgeRound(`Round ${roundNo}`, rid);
              if (ev.limit !== null) return limitStop(ev.limit);
              if (!ev.complete) return { stop: "evaluation failed after its one retry" };
            }
            // Gate before progress: a gate-passing candidate advances even on a tie.
            if (gatePasses(contract.target, ev.metric, at.checks, ev.covered) && at.seq >= floor) continue;
            const step = progress(era, ev.metric);
            era.counter = step.counter;
            if (step.improved) era.best = { candidate: at.candidate, metric: ev.metric };
          }
        });

      const contract0 = { criteria: p.criteria, rubric: p.rubric, target: p.target, checks: null };
      let outcome = yield* runEra(1, latest, contract0, null);
      let accepted = outcome.accepted ?? null;
      let stopReason = accepted ? null : outcome.stop ?? null;
      let recovery = null;
      let single = null;

      if (outcome.single !== undefined) {
        // review_rounds: 1 replaces the recheck and the score gate; no automatic recovery and no second scored round.
        single = outcome;
        stopReason = outcome.single === "verified" ? null : outcome.stop ?? `single-round verification incomplete: ${outcome.verification}`;
        recovery = { outcome: "not applicable", trigger: "review_rounds: 1", diagnosis: "the adopted one-round exception replaces rechecks", fix: "none", revised: null };
      } else if (accepted === null && p.continuation !== undefined) {
        recovery = { outcome: "spent", trigger: stopReason, diagnosis: `spent by prior run ${p.continuation.priorRun}`, fix: "none", revised: null };
      } else if (accepted === null) {
        // ----- the single automatic recovery -----
        yield* pausePoint("before-recovery");
        const committed = yield* T3.step("recovery/committed", { returns: Schema.Struct({ trigger: Schema.String, at: Schema.Number }) },
          Effect.sync(() => ({ trigger: stopReason, at: Date.now() })));
        const capSpent = !repairsLeft();
        const from = latest;
        const failed = (diagnosis) => ({ outcome: "fix-failed", diagnosis, fix: "none", candidate: from.candidate, checks: from.checks,
          buildable: true, revised: null, availableRoutes: [], spendCapReached: false });
        const g = yield* limits("recovery/limits", repairMs);
        let fix;
        let reported = false;
        if (outcome.limit === "deadline" || outcome.limit === "spend-cap" || g.stop !== null) {
          // An exhausted deadline or spend cap blocks every recovery action, setup included.
          fix = failed(`${limitStop(g.stop ?? outcome.limit).stop}: it blocks every recovery action`);
        } else if (test && p.test.recovery !== undefined) {
          const t = p.test.recovery;
          fix = { outcome: t.outcome, diagnosis: "synthetic", fix: "synthetic recovery", candidate: t.changes === false ? from.candidate : "test-recovery",
            checks: { passed: true, coverage: true, summary: "synthetic" }, buildable: true, availableRoutes: ROUTE_KEYS, spendCapReached: false,
            revised: t.target === undefined ? null : { reason: "synthetic target revision", target: t.target } };
          reported = true;
        } else {
          const ran = yield* T3.agent.try("recovery/fix", {
            thread: { threadId: p.invokerThread },
            timeout: `${g.left} millis`,
            quiet: "30 minutes",
            returns: Fix,
            brief: [
              `${head} The loop stopped incomplete: ${stopReason}.`,
              "This is the run's single automatic recovery; it has one step key and runs at most once.",
              "Follow skills/review/references/budget-exhaustion.md, 'One automatic recovery', steps 2 to 4: diagnose from the",
              "retained evidence (start no evaluator), fix the cause, and freeze the result.",
              `Start from the latest committed candidate ${from.candidate} (from ${from.source}); keep every required fix.`,
              capSpent ? `The repair-round limit (${roundCap}) is spent: only a setup-only fix that leaves the candidate unchanged may recover.`
                : "A fix that changes the candidate consumes one repair round, whatever its outcome.",
              deadline === NO_DEADLINE ? "" : `Run deadline: ${new Date(deadline).toISOString()}; this turn has ${Math.floor(g.left / 60000)} minute(s).`,
              "Permitted changes: repair strategy, implementation, setup, rubric, target (inside the scale), required checks (in",
              `revised.checks), and the primary reviewer from the standing routes (${STATIC_ORDER.join(", ")}) that are lineage-eligible`,
              "and available. A new provider or model, a user constraint, a repository gate, a permission, publication or scope change",
              "blocks it: return fix-failed.",
              "Findings from the latest evaluation:", findingsText(lastEval?.judges ?? [], true), "",
              "Submit with t3_submit_output: outcome (fixed or fix-failed), diagnosis, fix, candidate (the frozen commit to re-baseline),",
              "checks, buildable, and revised (null, or the changed target, rubric, criteria, checks or primary with the reason).",
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
        const fixed = commit(fix.candidate, fix.checks, `the recovery (${fix.outcome})`, false);
        const after = yield* limits("recovery/after", 1);
        const rv = fix.revised;
        const next = rv?.primary ?? primary;
        const blocked = fix.outcome !== "fixed" ? null
          : after.stop !== null ? limitStop(after.stop).stop
          : !fix.buildable ? "the fixing turn marked its candidate unbuildable"
          : changes && capSpent ? "a candidate-changing fix is blocked: the repair-round limit is spent"
          : rv?.target !== undefined && !targetFits(p.scale, rv.target) ? `revised target ${rv.target} is outside the scale`
          : rv?.primary !== undefined && (lineageBlocked(p, rv.primary) || modeOf(ROUTES[rv.primary], p.maxRuntimeMode) === null) ? `${rv.primary} is not an eligible primary`
          : available === null || !available.has(next) ? `${next} is not reported available now`
          : (p.companions ?? []).some((k) => available === null || !available.has(k)) ? "a companion is not reported available now"
          : null;
        if (blocked !== null) fix = { ...fix, outcome: "fix-failed", diagnosis: `${fix.diagnosis} (${blocked})` };
        recovery = { trigger: stopReason, at: committed.at, outcome: fix.outcome, diagnosis: fix.diagnosis, fix: fix.fix, revised: rv, candidate: fix.candidate };
        yield* pausePoint("after-recovery");
        if (fix.outcome === "fixed") {
          if (rv?.primary !== undefined) primary = rv.primary;
          const contract = { criteria: rv?.criteria ?? contract0.criteria, rubric: rv?.rubric ?? contract0.rubric,
            target: rv?.target ?? contract0.target, checks: rv?.checks ?? contract0.checks };
          const comparable = rv === null || Object.keys(rv).every((k) => k === "reason");
          outcome = yield* runEra(2, fixed, contract, {
            comparable,
            fix: `${fix.fix}${rv?.checks ? ` Required checks now: ${rv.checks}` : ""}`,
            ledger: { kind: "automatic", label: `Recovery${rv?.target !== undefined ? ` · ${p.target} → ${rv.target}` : ""}`,
              trigger: stopReason, diagnosis: fix.diagnosis, fix: fix.fix },
          });
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
          : finalCandidate(eras, floor, latest);
      const finalJudges = final.entry?.judges ?? [];
      const ledger = ledgerNow(status);
      const result = {
        run: id, test, status, final: { candidate: final.candidate, metric: final.metric, note: final.note, checks: final.entry?.checks ?? null },
        stopReason, recovery, repairsUsed, latest, requiredFixFloor: floor, single: single ? { outcome: single.single, verification: single.verification ?? null } : null,
        continuation: p.continuation ?? null, selection, history, ledger,
      };
      yield* tell("callback", [
        test ? "TEST RUN with synthetic scores. Report this result only." : "",
        `Result: ${status}${revisedPass ? ` (revised target ${eras[1].target}; the original target ${p.target} was not met)` : ""}`,
        `Final candidate: ${final.candidate} (${final.metric ?? "no score"}; ${final.note})`,
        final.entry?.checks ? `Checks on the final candidate: ${final.entry.checks.passed ? "pass" : "fail"}, coverage ${final.entry.checks.coverage ? "complete" : "incomplete"}: ${final.entry.checks.summary}` : "",
        latest.candidate !== final.candidate ? `Latest committed candidate: ${latest.candidate} from ${latest.source}${latest.requiredFix ? ", adds a required fix" : ""}; checks ${latest.checks?.passed ? "pass" : "fail or not run"}: ${latest.checks?.summary ?? "none"}. It has no complete score.` : "",
        stopReason ? `Stop: ${stopReason}` : "",
        recovery ? `Recovery: ${recovery.outcome} after "${recovery.trigger}" — ${recovery.diagnosis}${recovery.revised ? ` Revised: ${JSON.stringify(recovery.revised)}` : ""}` : "Recovery: not used",
        `Reviewer selection: ${selection.basis}${selection.gates.length ? `; gates: ${selection.gates.join("; ")}` : ""}`,
        `Repairs used: ${repairsUsed}${roundCap === null ? "" : ` of ${roundCap}`}${p.continuation ? ` (including ${p.continuation.repairsUsed} from run ${p.continuation.priorRun})` : ""}.`,
        /deadline|spend cap/.test(stopReason ?? "") ? "An explicit limit is exhausted: do no further work under it." : "",
        `Findings on the final candidate ${final.candidate}:`, finalJudges.length ? findingsText(finalJudges, true) : "- no complete evaluation of this candidate",
        "Judge receipts for the final candidate:", receiptsText(finalJudges),
        "Attempt history (every evaluation attempt and repair, in order):",
        ...history.map((h) => (h.kind === "evaluation"
          ? `- ${h.round} ${h.attempt} evaluation of ${h.candidate}: ` + h.judges.map((j) => `${j.key} ${j.status}${typeof j.score === "number" ? ` ${j.score}` : ""} `
            + `(${j.executedModel ?? "model unverified"}${j.problems.length ? `; ${j.problems.join("; ").slice(0, 160)}` : ""}; `
            + `${j.findings.map((f) => `${f.id} ${f.severity}`).join(", ") || "no findings"})`).join("; ")
          : `- ${h.round} repair from ${h.base} to ${h.candidate}: ${h.stop ? `stopped (${h.stop.reason})` : h.summary.slice(0, 200)}; checks `
            + `${h.checks.passed ? "pass" : "fail"}: ${h.checks.summary.slice(0, 120)}${h.addsRequiredFix ? "; adds a required fix" : ""}; dispositions `
            + `${h.dispositions.map((d) => `${d.id} ${d.disposition}: ${d.note.slice(0, 120)}`).join(" | ") || "none"}`
            + (h.verification ? `; verification ${h.verification.verified ? "passed" : "failed"}: ${h.verification.summary.slice(0, 200)}` : ""))),
        "",
        test ? "" : "Continue with skills/review-loop/SKILL.md from its delivery step, using this result. Write the ledger below to your score ledger and render the chart.",
        "Score ledger:", JSON.stringify(ledger),
      ]);
      return result;
    }),
);
