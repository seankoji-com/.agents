// @tested-t3 0.1.12-nightly.20261123.5124
// @start manual
//
// Durable bookkeeping for skills/vote/SKILL.md: seat routes, the shared seat
// deadline, ballot validation, the one blind re-ask, the DeepSeek substitute,
// executed-model checks and the 2/3 tally. Judgment stays in the skill (framing,
// authority, the invoker-seat qualification) and in agent steps (ballots and
// open-vote grouping).
//
// Start: POST a JSON packet to this workflow's `ballot` webhook with an
// `idempotency-key` header; the same key returns the same run. The invoking
// thread gets up to two turns: one asking it to report each seat thread's
// executedModel, then the result. The hook URL lives in a private curl config;
// never put it in a command line, a transcript or this file.
//
// Known host limit (T3 0.1.12 nightly): when a voter's turn dies, T3 relaunches
// it once with a fresh timeout. A ballot that lands after the shared deadline is
// discarded as late, so the deadline bounds what counts, not the wall clock.

const SEATS = ["opus", "sol", "neon"];
const LETTERS = ["A", "B", "C"];
const DEADLINE_MS = 5 * 60 * 1000;
// Covers stopping a turn and recording its result; not extra voting time.
const GRACE_MS = 5 * 1000;
// Voters run in the narrowest mode in which their provider can submit a ballot
// without a person approving it. Claude, Codex and OpenCode submit under
// approval-required. Antigravity asks for approval before t3_submit_output
// there (seen live on 23 November 2026), so its routes use auto-accept-edits.
const RUNTIME_MODE = "approval-required";
const ANTIGRAVITY_MODE = "auto-accept-edits";
const INTERACTION_MODE = "default";

// Routes in preference order. `paid` routes need the operator's authorisation.
const ROUTES = {
  opus: [
    { instanceId: "claudeAgent", model: "claude-opus-5-5", effort: { id: "effort", value: "high" }, billing: "subscription" },
    { instanceId: "antigravity", model: "claude-opus-5-5", effort: { id: "thought_level", value: "high" }, billing: "subscription", mode: ANTIGRAVITY_MODE },
  ],
  sol: [
    { instanceId: "codex", model: "gpt-6.2-sol", effort: { id: "reasoningEffort", value: "high" }, billing: "subscription" },
    { instanceId: "pi", model: "litellm-credit/api-gpt-6.2-sol", effort: { id: "thinking", value: "high" }, billing: "api-credit", paid: true },
  ],
  neon: [
    { instanceId: "antigravity", model: "gemini-4-neon", effort: { id: "thought_level", value: "high" }, billing: "subscription", mode: ANTIGRAVITY_MODE },
    { instanceId: "antigravity_burner", model: "agy-gemini-4-neon", effort: null, billing: "subscription", mode: ANTIGRAVITY_MODE },
    { instanceId: "pi", model: "litellm-credit/gemini-4-neon", effort: { id: "thinking", value: "high" }, billing: "api-credit", paid: true },
  ],
  deepseek: [
    { instanceId: "opencode", model: "litellm/deepseek-v4.1-flash", effort: { id: "variant", value: "high" }, billing: "litellm (unverified)" },
  ],
};

// The exact model IDs a host may record for each seat. Anything else conflicts.
const EXECUTED = {
  opus: ["claude-opus-5-5"],
  sol: ["gpt-6.2-sol", "litellm-credit/api-gpt-6.2-sol"],
  neon: ["gemini-4-neon", "agy-gemini-4-neon", "litellm-credit/gemini-4-neon"],
  deepseek: ["litellm/deepseek-v4.1-flash", "deepseek-v4.1-flash"],
};
// A voter's own claim: naming the seat's family alone is unverified, not a conflict.
// A claim that names another model, or any version other than the seat's, conflicts.
const FAMILY_WORDS = {
  opus: ["claude", "opus", "anthropic"],
  sol: ["gpt", "sol", "openai", "codex", "chatgpt"],
  neon: ["gemini", "neon", "google"],
  deepseek: ["deepseek"],
};
const EXACT_CLAIM = {
  opus: /\bopus[\s-]*5[.\s-]5\b/i,
  sol: /\b(?:gpt[\s-]*6\.2[\s-]*sol|sol[\s-]*6\.2)\b/i,
  neon: /\b(?:gemini[\s-]*4[\s-]*neon|neon[\s-]*4)\b/i,
  deepseek: /\bdeepseek[\s-]*v?4\.1[\s-]*flash\b/i,
};
const MODEL_WORDS = /\b(claude|opus|sonnet|haiku|fable|anthropic|gpt|chatgpt|sol|luna|astra|terra|codex|openai|gemini|neon|argon|hydrogen|carbon|google|deepseek|grok|qwen|glm|llama|mistral)\b/gi;

// The open-vote grouping step tries these in order.
const GROUPERS = [
  { instanceId: "claudeAgent", model: "claude-opus-5-5", effort: { id: "effort", value: "high" } },
  { instanceId: "codex", model: "gpt-6.2-sol", effort: { id: "reasoningEffort", value: "high" } },
  { instanceId: "antigravity", model: "claude-opus-5-5", effort: { id: "thought_level", value: "high" }, mode: ANTIGRAVITY_MODE },
];
// A voter never runs in a broader mode than its invoker allowed.
const MODE_RANK = { "approval-required": 0, "auto-accept-edits": 1, auto: 2, "full-access": 3 };

const HEDGE = /\b(abstain|abstaining|no preference|need(?:s)? more (?:info|information|context)|insufficient (?:info|information)|cannot (?:decide|choose|determine)|can't (?:decide|choose)|either (?:option|one) (?:is|would be) fine)\b/i;
// An imperative starts with a bare verb: not a pronoun, an article or a gerund.
// Code rejects only the clear cases; the grouping step judges the rest.
const NOT_IMPERATIVE = /^(?:i|we|you|it|this|that|these|those|the|a|an|my|our|there)\b/i;
const SEAT_NAMES = ["opus", "sol", "neon", "deepseek"];

const InvokerSeat = Schema.Struct({
  seat: Schema.Literals(SEATS),
  choice: Schema.optional(Schema.String),
  action: Schema.optional(Schema.String),
  label: Schema.optional(Schema.String),
  rationale: Schema.String,
  assumption: Schema.String,
  source: Schema.String,
});

const SyntheticBallot = Schema.Struct({
  seat: Schema.Literals(SEAT_NAMES),
  status: Schema.optional(Schema.Literals(["valid", "unavailable", "invalid", "late"])),
  choice: Schema.optional(Schema.String),
  action: Schema.optional(Schema.String),
  label: Schema.optional(Schema.String),
  rationale: Schema.optional(Schema.String),
  assumption: Schema.optional(Schema.String),
  model: Schema.optional(Schema.String),
});

const Test = Schema.Struct({
  // Replace the seats with these ballots. The result is labelled as a test.
  ballots: Schema.optional(Schema.Array(SyntheticBallot)),
  // Fail one step until this many seconds after it first runs, so the run pauses.
  pauseSeconds: Schema.optional(Schema.Number),
});

const Packet = Schema.Struct({
  invokerThread: Schema.String,
  kind: Schema.Literals(["closed", "open"]),
  question: Schema.String,
  options: Schema.optional(Schema.Array(Schema.String)),
  context: Schema.String,
  authorises: Schema.String,
  deadlineMinutes: Schema.optional(Schema.Number),
  paidRoutes: Schema.optional(Schema.Boolean),
  // A T3 project for voter and grouper threads. Defaults to T3's scratch project, so a
  // voter that may edit files cannot touch the invoker's repository.
  project: Schema.optional(Schema.String),
  // The invoker's own runtime mode: no voter runs in a broader one. The hook config is an
  // operator credential: the workflow cannot check this claim, so voters stay contained.
  maxRuntimeMode: Schema.Literals(["approval-required", "auto-accept-edits", "auto", "full-access"]),
  invokerSeat: Schema.optional(InvokerSeat),
  test: Schema.optional(Test),
});

const decodePacket = Schema.decodeUnknownSync(Packet);

// ---------- pure rules (no clock, no I/O) ----------

function packetProblems(p) {
  const problems = [];
  const options = p.options ?? [];
  if (!p.invokerThread.trim()) problems.push("invokerThread is empty");
  if (!p.question.trim()) problems.push("question is empty");
  if (!p.authorises.trim()) problems.push("authorises is empty");
  if (p.kind === "closed") {
    if (options.length < 2) problems.push("a closed vote needs at least two options");
    if (new Set(options).size !== options.length) problems.push("options repeat");
    if (options.some((o) => !o.trim())) problems.push("an option is empty");
  } else if (options.length > 0) {
    problems.push("an open vote takes no options");
  }
  if (p.deadlineMinutes !== undefined && !(p.deadlineMinutes > 0 && p.deadlineMinutes <= 5)) {
    problems.push("deadlineMinutes must be above 0 and at most 5");
  }
  const inv = p.invokerSeat;
  if (inv !== undefined) {
    if (!SEATS.includes(inv.seat)) problems.push("invokerSeat.seat must be opus, sol or neon");
    if (!inv.source.trim()) problems.push("invokerSeat.source is empty");
    for (const problem of ballotProblems(p, inv.seat, { ...inv, model: "" })) problems.push(`invokerSeat: ${problem}`);
  }
  const fixtures = p.test?.ballots;
  if (fixtures !== undefined) {
    if (p.invokerSeat !== undefined) problems.push("test.ballots replaces every seat; drop invokerSeat");
    const seats = fixtures.map((b) => b.seat);
    if (seats.length !== 3 || new Set(seats).size !== 3 || seats.some((s) => !SEAT_NAMES.includes(s))) {
      problems.push("test.ballots needs three distinct seats from opus, sol, neon and deepseek");
    }
  }
  return problems;
}

function oneLine(text) {
  return typeof text === "string" && text.trim() !== "" && !/[\r\n]/.test(text.trim());
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function modelConflict(seat, claim) {
  const text = (claim ?? "").trim();
  if (!text || !SEAT_NAMES.includes(seat)) return false;
  // Every mention of the seat's model, by name or by any recorded ID, is removed first.
  const forms = [EXACT_CLAIM[seat].source, ...EXECUTED[seat].map(escapeRegExp)];
  const mention = new RegExp(`(?:${forms.join("|")})`, "gi");
  let exact = false;
  let glued = false;
  const rest = text.replace(mention, (match, offset) => {
    exact = true;
    // A suffix glued to the exact name, such as "-preview", names a different model.
    if (/^[A-Za-z0-9_]|^-[A-Za-z0-9]/.test(text.slice(offset + match.length))) glued = true;
    return " ";
  });
  if (glued) return true;
  const named = (rest.match(MODEL_WORDS) ?? []).map((w) => w.toLowerCase());
  if (named.some((w) => !FAMILY_WORDS[seat].includes(w))) return true;
  // Another versioned name beside the exact one, as in "Opus 5.5 or Opus 4.6", conflicts.
  if (exact && new RegExp(`${MODEL_WORDS.source}[\\s-]*v?\\d`, "i").test(rest)) return true;
  // Family words alone are unverified, not a conflict; a family word with another version conflicts.
  return !exact && named.length > 0 && /\d/.test(rest);
}

function executedMatches(seat, model) {
  return EXECUTED[seat].includes(String(model).trim().toLowerCase());
}

function ballotProblems(p, seat, b) {
  const problems = [];
  if (p.kind === "closed") {
    if (!(p.options ?? []).includes(b.choice)) problems.push("choice is not exactly one listed option");
  } else {
    const action = typeof b.action === "string" ? b.action.trim() : "";
    if (!oneLine(action)) problems.push("action must be one non-empty sentence on one line");
    else if (/[.!?;]\s+\S/.test(action)) problems.push("action must be a single sentence");
    else if (NOT_IMPERATIVE.test(action)) problems.push("action must be an imperative sentence");
    else if (action.length > 600) problems.push("action is longer than 600 characters");
    if (!oneLine(b.label) || b.label.trim().length > 80) problems.push("label must be one short line");
  }
  if (typeof b.rationale !== "string" || !b.rationale.trim()) problems.push("rationale is empty");
  if (typeof b.assumption !== "string" || !b.assumption.trim()) problems.push("assumption is empty");
  const said = [b.action, b.label, b.rationale].filter((t) => typeof t === "string").join(" ");
  if (HEDGE.test(said)) problems.push("the ballot hedges, abstains or asks for more information");
  if (modelConflict(seat, b.model)) problems.push(`the voter's model claim "${b.model}" conflicts with the ${seat} seat`);
  return problems;
}

function choiceOf(p, b) {
  return p.kind === "closed" ? b.choice : b.action.trim();
}

function groupProblems(groups, letters) {
  const seen = groups.flat();
  if (groups.some((g) => g.length === 0)) return ["a group is empty"];
  if (seen.length !== letters.length || new Set(seen).size !== seen.length) return ["groups do not list each ballot once"];
  if (seen.some((l) => !letters.includes(l))) return ["groups name an unknown ballot"];
  return [];
}

function counts(s) {
  return s.status === "valid" || s.status === "invoker-existing";
}

function tally(p, seats, groups) {
  const valid = seats.filter(counts);
  const unverified = valid.filter((s) => s.blind === false || s.executed?.verified === false).map((s) => s.seat);
  if (valid.length < 3) {
    return { outcome: "incomplete", choice: null, reason: `${valid.length} valid ballot(s); a 2/3 majority needs three valid ballots`, dependsOn: [] };
  }
  let buckets;
  if (p.kind === "closed") {
    const byChoice = new Map();
    for (const s of valid) byChoice.set(s.ballot.choice, [...(byChoice.get(s.ballot.choice) ?? []), s]);
    buckets = [...byChoice.values()];
  } else {
    buckets = groups.map((g) => g.map((letter) => valid[LETTERS.indexOf(letter)]));
  }
  const winner = buckets.find((b) => b.length >= 2);
  if (winner === undefined) return { outcome: "split", choice: null, reason: "no two valid ballots match", dependsOn: [] };
  return {
    outcome: "majority",
    choice: choiceOf(p, winner[0].ballot),
    matched: winner.map((s) => ({ seat: s.seat, choice: choiceOf(p, s.ballot) })),
    reason: `${winner.length} of 3 valid ballots match`,
    // Seats that are not blind or not execution-verified, named only when fewer than two
    // blind, verified seats back the winning choice on their own.
    dependsOn: winner.filter((s) => !unverified.includes(s.seat)).length >= 2
      ? []
      : winner.map((s) => s.seat).filter((seat) => unverified.includes(seat)),
  };
}

// Host receipts, read by the invoker, for the turn that produced each ballot and
// for the invoker's own recommendation turn. A recorded model other than the
// seat's, or a recorded completion after the seat deadline, invalidates the
// seat. A missing receipt leaves the seat counted but execution-unverified.
// T3 gives workflow code no turn IDs, so which turn a receipt describes rests
// on the invoker's report; the result says so. The thread's run count, less the
// first turn and the workflow's re-ask, is T3's automatic format corrections.
function applyReceipts(seats, receipts, invokerModel) {
  return seats.map((s) => {
    if (s.status === "invoker-existing") {
      if (!invokerModel) return { ...s, executed: { model: null, verified: false } };
      const executed = { model: invokerModel, verified: true };
      return executedMatches(s.seat, invokerModel)
        ? { ...s, executed }
        : { ...s, executed, status: "invalid", problems: [`the recommendation turn ran ${invokerModel}, not the ${s.seat} seat's model`] };
    }
    if (s.thread === null || s.requested === null) return s;
    const r = receipts.find((x) => x.thread === s.thread);
    if (r === undefined) return { ...s, executed: { model: null, turn: null, completedAt: null, verified: false } };
    const corrections = typeof r.turns === "number" ? Math.max(0, r.turns - 1 - (s.reasked ? 1 : 0)) : null;
    const executed = {
      model: r.executedModel,
      turn: r.turnId,
      completedAt: r.completedAt,
      verified: Boolean(r.executedModel),
      turnBinding: "reported by the invoker",
      timing: r.completedAt ? "host" : "workflow clock only",
      corrections,
    };
    const finished = Date.parse(r.completedAt ?? "");
    const wrongModel = Boolean(r.executedModel) && !executedMatches(s.routeSeat, r.executedModel);
    const late = Number.isFinite(finished) && s.deadline !== undefined && finished > s.deadline;
    if (!counts(s) || (!wrongModel && !late)) return { ...s, executed };
    return {
      ...s,
      executed,
      status: wrongModel ? "invalid" : "late",
      ballot: null,
      problems: [
        ...s.problems,
        ...(wrongModel ? [`host executedModel ${r.executedModel} is not the seat's model`] : []),
        ...(late ? ["the host records the ballot turn finishing after the seat deadline"] : []),
      ],
    };
  });
}

function packetText(p, deadlineMinutes) {
  const lines = [`Question: ${p.question}`, ""];
  if (p.kind === "closed") {
    lines.push("Vote type: closed. Choose exactly one option, copied verbatim.", "Options, in order:");
    (p.options ?? []).forEach((o, i) => lines.push(`${i + 1}. ${o}`));
  } else {
    lines.push(
      "Vote type: open. Propose one action as one imperative sentence that names the verb,",
      "the object and every material parameter, plus a short label of a few words.",
    );
  }
  lines.push(
    "",
    "Constraints, evidence, definitions and authority:",
    p.context,
    "",
    `A 2/3 majority authorises: ${p.authorises}`,
    `Your deadline: ${deadlineMinutes} minute(s) from dispatch.`,
  );
  return lines.join("\n");
}

function voterBrief(p, deadlineMinutes) {
  return [
    "You are one of three blind voters. Answer from this packet alone.",
    "Do not read files, run commands, browse, delegate or use any tool except `t3_submit_output`.",
    "Do not hedge, abstain or ask for more information.",
    "",
    packetText(p, deadlineMinutes),
    "",
    "Submit your ballot with `t3_submit_output`:",
    p.kind === "closed"
      ? "- choice: exactly one option above, copied verbatim."
      : "- action: one imperative sentence with verb, object and every material parameter.\n- label: a few words.",
    "- rationale: two to four sentences.",
    "- assumption: the key assumption your choice rests on.",
    "- model: your own model name and version as you know it.",
  ].join("\n");
}

function ballotSchema(p) {
  const shared = { rationale: Schema.String, assumption: Schema.String, model: Schema.String };
  return p.kind === "closed"
    ? Schema.Struct({ choice: Schema.Literals(p.options), ...shared })
    : Schema.Struct({ action: Schema.String, label: Schema.String, ...shared });
}

function modelSelection(route) {
  return { instanceId: route.instanceId, model: route.model, ...(route.effort === null ? {} : { options: [route.effort] }) };
}

function modeOf(route) {
  return route.mode ?? RUNTIME_MODE;
}

function allowed(route, ceiling) {
  return MODE_RANK[modeOf(route)] <= MODE_RANK[ceiling];
}

function requested(route) {
  return {
    provider: route.instanceId,
    model: route.model,
    effort: route.effort === null ? "not applicable (route exposes no effort option)" : `${route.effort.id}=${route.effort.value}, unverified`,
    billing: route.billing,
    runtimeMode: route.mode ?? RUNTIME_MODE,
  };
}

// T3 reports a typed result that never fit as a failed agent step. That is a
// non-ballot, which earns the one blind re-ask, not a route failure.
function isNonBallot(reason) {
  return /did not fit|did not return a result|ended with none accepted|could not be asked again/.test(reason ?? "");
}

function resultText(p, r) {
  const t = r.tally;
  const result = t.outcome === "majority"
    ? `${t.choice} — 2/3 majority${t.dependsOn.length ? ` (rests on ${t.dependsOn.join(", ")}: not blind or execution-unverified)` : ""}`
    : t.outcome === "split" ? "No majority (complete split)" : `No majority (incomplete: ${t.reason})`;
  const seatLines = r.seats.map((s) => {
    const req = s.requested
      ? `${s.requested.provider}/${s.requested.model}, ${s.requested.effort}, ${s.requested.billing}, ${s.requested.runtimeMode}`
      : s.status === "invoker-existing" ? `invoker's own thread; source: ${s.source}`
      : s.synthetic ? "synthetic" : "no route";
    const what = s.ballot ? choiceOf(p, s.ballot) : "-";
    const why = s.ballot?.rationale ?? s.problems.join("; ");
    const e = s.executed;
    const exec = e
      ? `executedModel ${e.model ?? "null"} ${e.verified ? "verified" : "unverified"}`
        + (e.turn ? ` (turn ${e.turn}, ${e.turnBinding}; completed ${e.completedAt ?? "unknown"}, timing from ${e.timing})` : "")
      : s.receiptProblem ? `no host receipt: ${s.receiptProblem}` : null;
    const marks = [
      s.status,
      s.blind === false ? "not blind" : null,
      s.substitutes ? `substitute for ${s.substitutes}` : null,
      s.reasked ? "re-asked once" : null,
      e && e.corrections !== null && e.corrections !== undefined ? `T3 format corrections: ${e.corrections}` : null,
      exec,
      s.thread ? `thread ${s.thread}` : null,
    ].filter(Boolean).join(", ");
    return `- ${s.seat} (${req}): ${what} — ${why} [${marks}]`;
  });
  return [
    r.test ? "TEST RUN with synthetic or injected input. This is not a vote: do not act on it." : null,
    `Vote: ${p.question}`,
    `Result: ${result}`,
    "Seats:",
    ...seatLines,
    `Grouping (open only): ${r.grouping ?? "not needed"}`,
  ].filter((l) => l !== null).join("\n");
}

// ---------- workflow ----------

export default T3.workflow(
  "vote",
  { version: 5, payload: T3.WebhookRequest, triggers: [T3.webhook("ballot")] },
  (input, { id }) =>
    Effect.gen(function* () {
      const parsed = yield* T3.step.try("packet", { returns: Packet }, Effect.try(() => decodePacket(JSON.parse(input.body))));
      if (parsed.outcome === "failed") {
        // Tell the invoker when the body names its thread, so a bad packet does not vanish.
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
            `[T3 workflow vote, run ${id}]`,
            "Packet rejected before any voter was dispatched. Nothing was decided: do not act on this.",
            `- ${parsed.reason.slice(0, 600)}`,
            "Fix the packet and start a new vote with a new idempotency key.",
          ].join("\n") });
        }
        return yield* T3.stop(`packet rejected: ${parsed.reason}`);
      }
      const p = parsed.value;
      const test = p.test !== undefined;
      yield* T3.title(`${test ? "[test] " : ""}vote: ${p.question.slice(0, 80)}`);

      // The pausing form: a failed delivery pauses the run and retries under the same step key.
      const tell = (name, lines) =>
        T3.agent(name, { thread: { threadId: p.invokerThread }, brief: [`[T3 workflow vote, run ${id}]`, ...lines].join("\n") });

      const problems = packetProblems(p);
      if (problems.length > 0) {
        yield* tell("callback", [
          "Packet rejected; no voter was dispatched. Nothing was decided: do not act on this.",
          ...problems.map((x) => `- ${x}`),
          "Fix the packet and start a new vote with a new idempotency key.",
        ]);
        return { run: id, outcome: "rejected", problems };
      }

      const minutes = p.deadlineMinutes ?? DEADLINE_MS / 60000;
      const limitMs = Math.round(minutes * 60000);
      const brief = voterBrief(p, minutes);
      const returns = ballotSchema(p);
      const project = p.project ?? `${process.env.HOME}/.t3/scratch`;
      const now = (name) => T3.step(name, { returns: Schema.Number }, Effect.sync(() => Date.now()));
      const budget = (name, deadline) => T3.step(name, { returns: Schema.Number }, Effect.sync(() => deadline - Date.now()));

      // One dispatched voter through its routes, with one blind re-ask, inside `deadline`.
      const runSeat = (seat, routeSeat, tag, deadline) =>
        Effect.gen(function* () {
          const attempts = [];
          const routes = ROUTES[routeSeat].filter((r) => !r.paid || p.paidRoutes === true);
          for (const route of ROUTES[routeSeat].filter((r) => !routes.includes(r) || !allowed(r, p.maxRuntimeMode))) {
            attempts.push({ route: requested(route), outcome: "skipped",
              reason: routes.includes(route) ? `needs ${modeOf(route)}, above the invoker's ${p.maxRuntimeMode}`
                : "paid route without operator authorisation" });
          }
          for (const [index, route] of routes.entries()) {
            if (!allowed(route, p.maxRuntimeMode)) continue;
            const key = `seat/${tag}/${index}`;
            const left = yield* budget(`${key}/budget`, deadline);
            if (left <= 0) {
              attempts.push({ route: requested(route), outcome: "skipped", reason: "the seat deadline passed" });
              break;
            }
            const first = yield* T3.agent.try(key, {
              project,
              model: modelSelection(route),
              title: `vote ${seat}: ${p.question.slice(0, 60)}`,
              brief,
              returns,
              timeout: `${left} millis`,
              runtimeMode: modeOf(route),
              interactionMode: INTERACTION_MODE,
            });
            const thread = first.thread?.threadId ?? null;
            let answer = first;
            let reasked = false;
            let problems = first.outcome === "done" ? ballotProblems(p, routeSeat, first.value) : [];
            const reaskable = (first.outcome === "done" && problems.length > 0)
              || (first.outcome === "failed" && thread !== null && isNonBallot(first.reason));
            if (reaskable) {
              const again = yield* budget(`${key}/reask/budget`, deadline);
              if (again > 0) {
                reasked = true;
                const why = first.outcome === "done" ? problems.join("; ") : first.reason;
                answer = yield* T3.agent.try(`${key}/reask`, {
                  thread: { threadId: thread },
                  brief: [`Your answer was not a valid ballot: ${why}`,
                    "This is your one re-ask. Use the same packet and submit exactly one ballot with `t3_submit_output`.", "", brief].join("\n"),
                  returns,
                  timeout: `${again} millis`,
                });
                problems = answer.outcome === "done" ? ballotProblems(p, routeSeat, answer.value) : [];
              }
            }
            // A first check on the workflow's clock; the host's turn completion time decides later.
            const ended = yield* now(`${key}/ended`);
            const late = ended > deadline + GRACE_MS;
            const base = { seat, routeSeat, requested: requested(route), reasked, thread, blind: true, deadline };
            if (answer.outcome === "done") {
              const status = late ? "late" : problems.length > 0 ? "invalid" : "valid";
              attempts.push({ route: requested(route), outcome: status, thread });
              return { ...base, status, ballot: status === "valid" ? answer.value : null,
                problems: late ? ["the ballot came after the seat deadline"] : problems, attempts };
            }
            attempts.push({ route: requested(route), outcome: "failed", reason: answer.reason, thread });
            if (reaskable || late) {
              // The voter answered without a ballot, or time ran out: the seat failed.
              return { ...base, status: late ? "late" : "invalid", ballot: null, problems: [answer.reason], attempts };
            }
            // Could not start, died or timed out before answering: try the next eligible route.
          }
          return { seat, routeSeat, status: "unavailable", ballot: null, problems: attempts.map((a) => a.reason ?? a.outcome),
            requested: null, reasked: false, thread: null, blind: true, deadline, attempts };
        });

      // The invoker reads each listed seat thread's host record; code then checks it.
      const Receipts = Schema.Struct({
        seats: Schema.Array(Schema.Struct({
          thread: Schema.String,
          turnId: Schema.NullOr(Schema.String),
          executedModel: Schema.NullOr(Schema.String),
          completedAt: Schema.NullOr(Schema.String),
          turns: Schema.NullOr(Schema.Number),
        })),
        invokerModel: Schema.NullOr(Schema.String),
      });
      const verify = (name, listed, askInvoker) =>
        Effect.gen(function* () {
          if (listed.length === 0 && !askInvoker) return { seats: [], invokerModel: null };
          const read = yield* T3.agent.try(name, {
            thread: { threadId: p.invokerThread },
            timeout: "10 minutes",
            returns: Receipts,
            brief: [
              `[T3 workflow vote, run ${id}] Host receipts before the tally. Do not act on the vote; do nothing else.`,
              "For each thread below, read its activity with t3_thread_read and find the turn that submitted the",
              "ballot with t3_submit_output (the last such turn). Report that turn's ID, the executedModel the host",
              "recorded for it, when it completed as an ISO 8601 time, and as turns the number of runs the thread has.",
              "Use null for anything the host does not show.",
              ...listed.map((s) => `- ${s.thread} (seat ${s.seat}, requested ${s.requested?.model ?? "?"})`),
              askInvoker
                ? `Also report as invokerModel the executedModel of your own turn that made the recommendation cited as: ${p.invokerSeat.source}`
                : "Report invokerModel as null.",
              "Submit with t3_submit_output.",
            ].join("\n"),
          });
          return read.outcome === "done" ? read.value : { seats: [], invokerModel: null, failed: read.reason };
        });

      let seats;
      if (p.test?.ballots !== undefined) {
        seats = p.test.ballots.map((b) => {
          const status = b.status ?? "valid";
          const shaped = status === "valid" ? ballotProblems(p, b.seat, b) : [];
          return { seat: b.seat, routeSeat: b.seat, status: shaped.length ? "invalid" : status,
            ballot: status === "valid" && !shaped.length ? b : null, problems: shaped, requested: null,
            reasked: false, thread: null, blind: true, attempts: [], synthetic: true };
        });
      } else {
        const opened = yield* now("clock/open");
        seats = yield* Effect.all(
          SEATS.map((seat) => {
            const inv = p.invokerSeat;
            if (inv !== undefined && inv.seat === seat) {
              return Effect.succeed({ seat, routeSeat: seat, status: "invoker-existing", ballot: { ...inv, model: "" },
                problems: [], requested: null, reasked: false, thread: p.invokerThread, blind: false, source: inv.source, attempts: [] });
            }
            return runSeat(seat, seat, seat, opened + limitMs);
          }),
          { concurrency: "unbounded" },
        );
        const unavailable = seats.filter((s) => s.status === "unavailable");
        const gone = unavailable.length === 1 ? unavailable[0] : null;
        const tries = [];
        let subDeadline = null;
        if (gone !== null) {
          // One substitute seat with one deadline; a failed first try gets one retry inside it.
          subDeadline = (yield* now("clock/substitute")) + limitMs;
          tries.push(yield* runSeat("deepseek", "deepseek", "deepseek/0", subDeadline));
        }
        const place = () => (tries.length === 0 ? seats : seats.map((s) => (s === gone
          ? { ...tries[tries.length - 1], substitutes: gone.seat, replaced: gone, attempts: tries.flatMap((t) => t.attempts) }
          : s)));
        let placed = place();
        const listed = placed.filter((s) => s.thread !== null && s.status !== "invoker-existing");
        let receipts = yield* verify("receipts", listed, p.invokerSeat !== undefined);
        placed = applyReceipts(placed, receipts.seats, receipts.invokerModel);
        const sub = placed.find((s) => s.substitutes !== undefined);
        if (sub !== undefined && !counts(sub)) {
          // The first substitute failed, including on its host receipt: one retry, then check it too.
          tries.push(yield* runSeat("deepseek", "deepseek", "deepseek/1", subDeadline));
          const retried = place().find((s) => s.substitutes !== undefined);
          const again = yield* verify("receipts/substitute-retry", retried.thread === null ? [] : [retried], false);
          const [checked] = applyReceipts([retried], again.seats, null);
          placed = placed.map((s) => (s.substitutes !== undefined ? checked : s));
          receipts = { ...receipts, retry: again };
        }
        seats = placed;
        if (receipts.failed) seats = seats.map((s) => ({ ...s, receiptProblem: receipts.failed }));
      }

      if (p.test?.pauseSeconds !== undefined) {
        // Test hook: pause the run before the tally so an operator can resume it.
        const armed = yield* now("test/armed");
        yield* T3.step("test/pause", { returns: Schema.Number }, Effect.suspend(() => {
          const wait = armed + p.test.pauseSeconds * 1000 - Date.now();
          return wait > 0
            ? Effect.fail(new Error(`test pause: resume after ${Math.ceil(wait / 1000)} more second(s)`))
            : Effect.succeed(Date.now());
        }));
      }

      // Open votes: a judgment step groups equivalent ballots; code counts the groups.
      const Grouped = Schema.Struct({
        groups: Schema.Array(Schema.Array(Schema.String)),
        notActions: Schema.Array(Schema.String),
        reasoning: Schema.String,
      });
      const groupOnce = (tag, ballots) =>
        Effect.gen(function* () {
          const listed = ballots.map((s, i) => `${LETTERS[i]}. ${s.ballot.action.trim()}`).join("\n");
          const failures = [];
          for (const [index, g] of GROUPERS.entries()) {
            if (!allowed(g, p.maxRuntimeMode)) {
              failures.push(`${g.instanceId}/${g.model}: needs ${modeOf(g)}`);
              continue;
            }
            const r = yield* T3.agent.try(`${tag}/${index}`, {
              project,
              model: modelSelection(g),
              title: `vote grouping: ${p.question.slice(0, 60)}`,
              runtimeMode: modeOf(g),
              interactionMode: INTERACTION_MODE,
              timeout: "5 minutes",
              returns: Grouped,
              brief: [
                "Group these proposed actions. Use no tool except `t3_submit_output`.",
                "First list in `notActions` every letter that is not one concrete imperative action, such as a",
                "judgment, a description or a statement of what is safe. Group every letter, including those.",
                "Two actions match only when the verb, the object and every material parameter agree,",
                "and neither omits or rules out a step the other has. A material parameter is any",
                "parameter either sentence states. Wording does not matter. If matching needs argument,",
                "or one action is a superset of another, they do not match. Use the definitions and",
                "constraints below to tell whether two names refer to the same thing.",
                "",
                `Question: ${p.question}`,
                "",
                "Constraints, evidence, definitions and authority:",
                p.context,
                "",
                listed,
                "",
                "Submit `groups`: every letter exactly once, matching letters together, for example [[\"A\",\"C\"],[\"B\"]].",
                "Submit `reasoning`: one line per group.",
              ].join("\n"),
            });
            if (r.outcome !== "done") {
              failures.push(`${g.instanceId}/${g.model}: ${r.reason}`);
              continue;
            }
            const shape = [...groupProblems(r.value.groups, LETTERS),
              ...(r.value.notActions.every((l) => LETTERS.includes(l)) ? [] : ["notActions names an unknown ballot"])];
            if (shape.length === 0) {
              // A repeated letter names one ballot once.
              const value = { ...r.value, notActions: [...new Set(r.value.notActions)] };
              return { ok: true, value, by: `${g.instanceId}/${g.model}`, thread: r.thread?.threadId ?? null };
            }
            failures.push(`${g.instanceId}/${g.model}: ${shape.join("; ")}`);
          }
          return { ok: false, failures };
        });

      let groups = [];
      let grouping = null;
      let verdict = null;
      if (p.kind === "open" && seats.filter(counts).length === 3) {
        let pass = yield* groupOnce("group", seats.filter(counts));
        const flagged = pass.ok ? pass.value.notActions.map((l) => seats.filter(counts)[LETTERS.indexOf(l)]) : [];
        if (flagged.length > 0) {
          // A ballot judged not to be an action gets the seat's one re-ask, inside its deadline.
          for (const s of flagged) {
            const left = s.reasked || s.thread === null || s.status !== "valid" ? 0
              : yield* budget(`seat/${s.seat}/action-reask/budget`, s.deadline);
            let fixed = null;
            if (left > 0) {
              const again = yield* T3.agent.try(`seat/${s.seat}/action-reask`, {
                thread: { threadId: s.thread },
                brief: ["Your action was judged not to be one concrete imperative action. This is your one re-ask.",
                  "Use the same packet and submit exactly one ballot with `t3_submit_output`.", "", brief].join("\n"),
                returns,
                timeout: `${left} millis`,
              });
              const ended = yield* now(`seat/${s.seat}/action-reask/ended`);
              if (again.outcome === "done" && ballotProblems(p, s.routeSeat, again.value).length === 0 && ended <= s.deadline + GRACE_MS) {
                fixed = again.value;
              }
            }
            seats = seats.map((x) => (x !== s ? x : fixed
              ? { ...x, ballot: fixed, reasked: true, actionReasked: true }
              : { ...x, status: "invalid", ballot: null, reasked: x.reasked || left > 0,
                problems: [...x.problems, "the grouping step found no concrete imperative action"] }));
          }
          // A replacement ballot needs its own host receipt: the earlier one described the first turn.
          const replaced = seats.filter((x) => x.actionReasked && counts(x));
          if (replaced.length > 0) {
            const again = yield* verify("receipts/action-reask", replaced, false);
            const checked = applyReceipts(replaced.map((x) => ({ ...x, executed: undefined })), again.seats, null);
            seats = seats.map((x) => checked.find((c) => c.seat === x.seat && c.thread === x.thread) ?? x);
          }
          if (seats.filter(counts).length === 3) {
            pass = yield* groupOnce("group/again", seats.filter(counts));
            const still = pass.ok ? new Set(pass.value.notActions.map((l) => seats.filter(counts)[LETTERS.indexOf(l)])) : new Set();
            seats = seats.map((x) => (still.has(x)
              ? { ...x, status: "invalid", ballot: null, problems: [...x.problems, "the grouping step found no concrete imperative action"] }
              : x));
          }
        }
        if (pass.ok) {
          groups = pass.value.groups;
          grouping = `${JSON.stringify(groups)} — ${pass.value.reasoning} (by ${pass.by}${pass.thread ? `, thread ${pass.thread}` : ""})`
            + (pass.value.notActions.length ? ` — not actions: ${pass.value.notActions.join(", ")}` : "");
        } else if (seats.filter(counts).length === 3) {
          grouping = `failed: ${pass.failures.join("; ")}`;
          verdict = { outcome: "incomplete", choice: null, reason: `open-vote grouping failed: ${pass.failures.join("; ")}`, dependsOn: [] };
        }
      }
      verdict = verdict ?? tally(p, seats, groups);

      const result = { run: id, test, packet: packetText(p, minutes), seats, grouping, tally: verdict };
      yield* tell("callback", [
        resultText(p, result),
        "",
        test
          ? "Report this test result only."
          : [
            "Continue with skills/vote/SKILL.md from 'Act or return', using this result and its labels.",
            `Act at most once for vote run ${id}: if this thread already shows an action taken for this run,`,
            "report that action instead of acting again.",
          ].join("\n"),
      ]);
      return result;
    }),
);
