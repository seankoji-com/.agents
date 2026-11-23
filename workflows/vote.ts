// @tested-t3 0.1.12-nightly.20261123.5124
// @start manual
//
// Durable bookkeeping for skills/vote/SKILL.md: seat routes, the shared seat
// deadline, ballot validation, the one blind re-ask, the DeepSeek substitute and
// the 2/3 tally. Judgment stays in the skill (framing, authority, the
// invoker-seat qualification) and in agent steps (ballots, open-vote grouping).
//
// Start: POST a JSON packet to this workflow's webhook with an `idempotency-key`
// header; the same key returns the same run. The result comes back as one turn
// in the invoking thread. The hook URL lives in a private curl config; never
// put it in a command line, a transcript or this file.

const SEATS = ["opus", "sol", "neon"];
const LETTERS = ["A", "B", "C"];
const DEADLINE_MS = 5 * 60 * 1000;
const GRACE_MS = 15 * 1000;
const RUNTIME_MODE = "approval-required";
const INTERACTION_MODE = "default";

// Routes in preference order. `paid` routes need the operator's authorisation.
const ROUTES = {
  opus: [
    { instanceId: "claudeAgent", model: "claude-opus-5-5", effort: { id: "effort", value: "high" }, billing: "subscription" },
    { instanceId: "antigravity", model: "claude-opus-5-5", effort: { id: "thought_level", value: "high" }, billing: "subscription" },
  ],
  sol: [
    { instanceId: "codex", model: "gpt-6.2-sol", effort: { id: "reasoningEffort", value: "high" }, billing: "subscription" },
    { instanceId: "pi", model: "litellm-credit/api-gpt-6.2-sol", effort: { id: "thinking", value: "high" }, billing: "api-credit", paid: true },
  ],
  neon: [
    { instanceId: "antigravity", model: "gemini-4-neon", effort: { id: "thought_level", value: "high" }, billing: "subscription" },
    { instanceId: "antigravity_burner", model: "agy-gemini-4-neon", effort: null, billing: "subscription" },
    { instanceId: "pi", model: "litellm-credit/gemini-4-neon", effort: { id: "thinking", value: "high" }, billing: "api-credit", paid: true },
  ],
  deepseek: [
    { instanceId: "opencode", model: "litellm/deepseek-v4.1-flash", effort: { id: "variant", value: "high" }, billing: "litellm (unverified)" },
  ],
};

// A voter's own model claim conflicts when it names another family and not its own.
const FAMILY = {
  opus: ["claude", "opus", "anthropic"],
  sol: ["gpt", "sol", "openai", "codex"],
  neon: ["gemini", "neon", "google"],
  deepseek: ["deepseek"],
};

const GROUPER = {
  instanceId: "claudeAgent",
  model: "claude-opus-5-5",
  effort: { id: "effort", value: "high" },
};

const InvokerSeat = Schema.Struct({
  seat: Schema.String,
  choice: Schema.optional(Schema.String),
  action: Schema.optional(Schema.String),
  label: Schema.optional(Schema.String),
  rationale: Schema.String,
  assumption: Schema.optional(Schema.String),
  source: Schema.String,
});

const SyntheticBallot = Schema.Struct({
  seat: Schema.String,
  status: Schema.optional(Schema.String),
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
  project: Schema.optional(Schema.String),
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
    const shaped = ballotProblems(p, inv.seat, { ...inv, model: "" });
    for (const problem of shaped) problems.push(`invokerSeat: ${problem}`);
  }
  if (p.test?.ballots !== undefined && p.invokerSeat !== undefined) {
    problems.push("test.ballots replaces every seat; drop invokerSeat");
  }
  return problems;
}

function oneLine(text) {
  return typeof text === "string" && text.trim() !== "" && !/[\r\n]/.test(text.trim());
}

function ballotProblems(p, seat, b) {
  const problems = [];
  if (p.kind === "closed") {
    if (!(p.options ?? []).includes(b.choice)) problems.push("choice is not exactly one listed option");
  } else {
    if (!oneLine(b.action)) problems.push("action must be one non-empty sentence on one line");
    else if (b.action.trim().length > 600) problems.push("action is longer than 600 characters");
    if (!oneLine(b.label) || b.label.trim().length > 80) problems.push("label must be one short line");
  }
  if (typeof b.rationale !== "string" || !b.rationale.trim()) problems.push("rationale is empty");
  const claim = (b.model ?? "").toLowerCase();
  const own = FAMILY[seat] ?? [];
  const other = Object.entries(FAMILY).filter(([name]) => name !== seat).flatMap(([, words]) => words);
  if (claim && !own.some((w) => claim.includes(w)) && other.some((w) => claim.includes(w))) {
    problems.push(`the voter's model claim "${b.model}" conflicts with the ${seat} seat`);
  }
  return problems;
}

function choiceOf(p, b) {
  return p.kind === "closed" ? b.choice : b.action.trim();
}

// Groups for an open vote are letters; a closed vote groups identical labels.
function groupProblems(groups, letters) {
  const seen = groups.flat();
  if (groups.some((g) => g.length === 0)) return ["a group is empty"];
  if (seen.length !== letters.length || new Set(seen).size !== seen.length) return ["groups do not list each ballot once"];
  if (seen.some((l) => !letters.includes(l))) return ["groups name an unknown ballot"];
  return [];
}

function tally(p, seats, groups) {
  const valid = seats.filter((s) => s.status === "valid" || s.status === "invoker-existing");
  const unverified = valid.filter((s) => s.blind === false).map((s) => s.seat);
  if (valid.length < 3) {
    return {
      outcome: "incomplete",
      choice: null,
      reason: `${valid.length} valid ballot(s); a 2/3 majority needs three valid ballots`,
      dependsOn: [],
      unverified,
    };
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
  if (winner === undefined) {
    return { outcome: "split", choice: null, reason: "no two valid ballots match", dependsOn: [], unverified };
  }
  return {
    outcome: "majority",
    choice: choiceOf(p, winner[0].ballot),
    matched: winner.map((s) => ({ seat: s.seat, choice: choiceOf(p, s.ballot) })),
    reason: `${winner.length} of 3 valid ballots match`,
    dependsOn: winner.filter((s) => s.blind === false).map((s) => s.seat),
    unverified,
  };
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
    "- model: your own model name as you know it.",
  ].join("\n");
}

function ballotSchema(p) {
  const shared = { rationale: Schema.String, assumption: Schema.String, model: Schema.String };
  return p.kind === "closed"
    ? Schema.Struct({ choice: Schema.Literals(p.options), ...shared })
    : Schema.Struct({ action: Schema.String, label: Schema.String, ...shared });
}

function modelSelection(route) {
  return {
    instanceId: route.instanceId,
    model: route.model,
    ...(route.effort === null ? {} : { options: [route.effort] }),
  };
}

function requested(route) {
  return {
    provider: route.instanceId,
    model: route.model,
    effort: route.effort === null ? "not applicable (route exposes no effort option)" : `${route.effort.id}=${route.effort.value}`,
    billing: route.billing,
  };
}

// T3 reports a typed result that never fit as a failed agent step. That is a
// non-ballot, which earns the one blind re-ask, not a route failure.
function isNonBallot(reason) {
  return /did not fit|did not return a result|ended with none accepted|could not be asked again/.test(reason ?? "");
}

function resultText(p, r) {
  const head = r.test ? "TEST RUN with synthetic or injected input; not a vote." : null;
  const result = r.tally.outcome === "majority"
    ? `${r.tally.choice} — 2/3 majority${r.tally.dependsOn.length ? ` (depends on ${r.tally.dependsOn.join(", ")}: invoker-existing, not blind)` : ""}`
    : r.tally.outcome === "split" ? "No majority (complete split)" : `No majority (incomplete: ${r.tally.reason})`;
  const seatLines = r.seats.map((s) => {
    const req = s.requested ? `${s.requested.provider}/${s.requested.model}, ${s.requested.effort}, ${s.requested.billing}` : "no route";
    const what = s.ballot ? choiceOf(p, s.ballot) : "-";
    const why = s.ballot?.rationale ?? s.problems.join("; ");
    const marks = [s.status, s.blind === false ? "not blind" : null, s.reasked ? "re-asked once" : null, s.thread ? `thread ${s.thread}` : null]
      .filter(Boolean).join(", ");
    return `- ${s.seat} (${req}): ${what} — ${why} [${marks}]`;
  });
  return [
    head,
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
  { version: 1, payload: T3.WebhookRequest, triggers: [T3.webhook("start")] },
  (input, { id }) =>
    Effect.gen(function* () {
      const parsed = yield* T3.step.try(
        "packet",
        { returns: Packet },
        Effect.try(() => decodePacket(JSON.parse(input.body))),
      );
      if (parsed.outcome === "failed") {
        return yield* T3.stop(`packet rejected: ${parsed.reason}`);
      }
      const p = parsed.value;
      const problems = packetProblems(p);
      const test = p.test !== undefined;
      yield* T3.title(`${test ? "[test] " : ""}vote: ${p.question.slice(0, 80)}`);

      const callback = (text) =>
        T3.agent.try("callback", {
          thread: { threadId: p.invokerThread },
          brief: [
            `[T3 workflow vote, run ${id}]`,
            text,
            "",
            "Continue with skills/vote/SKILL.md from 'Act or return'. Read each seat thread",
            "with t3_thread_read to record executedModel; label any null or missing value unverified.",
          ].join("\n"),
        });

      if (problems.length > 0) {
        yield* callback(`Packet rejected; no voter was dispatched:\n- ${problems.join("\n- ")}`);
        return { run: id, outcome: "rejected", problems };
      }

      const minutes = p.deadlineMinutes ?? DEADLINE_MS / 60000;
      const limitMs = Math.round(minutes * 60000);
      const brief = voterBrief(p, minutes);
      const returns = ballotSchema(p);
      const project = p.project ?? `${process.env.HOME}/.agents`;
      const now = (name) => T3.step(name, { returns: Schema.Number }, Effect.sync(() => Date.now()));
      const opened = yield* now("clock/open");

      // Run one seat through its routes, a shared deadline and one blind re-ask.
      const runSeat = (seat, routeSeat, tag, deadline) =>
        Effect.gen(function* () {
          const attempts = [];
          const routes = ROUTES[routeSeat].filter((r) => !r.paid || p.paidRoutes === true);
          for (const [index, route] of routes.entries()) {
            const key = `seat/${tag}/${index}`;
            const left = yield* T3.step(`${key}/budget`, { returns: Schema.Number }, Effect.sync(() => deadline - Date.now()));
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
              runtimeMode: RUNTIME_MODE,
              interactionMode: INTERACTION_MODE,
            });
            const thread = first.thread?.threadId ?? null;
            let answer = first;
            let reasked = false;
            let problems = first.outcome === "done" ? ballotProblems(p, routeSeat, first.value) : [];
            const reaskable = (first.outcome === "done" && problems.length > 0)
              || (first.outcome === "failed" && thread !== null && isNonBallot(first.reason));
            if (reaskable) {
              const leftAgain = yield* T3.step(`${key}/reask/budget`, { returns: Schema.Number }, Effect.sync(() => deadline - Date.now()));
              if (leftAgain > 0) {
                reasked = true;
                const why = first.outcome === "done" ? problems.join("; ") : first.reason;
                answer = yield* T3.agent.try(`${key}/reask`, {
                  thread: { threadId: thread },
                  brief: [
                    `Your answer was not a valid ballot: ${why}`,
                    "This is your one re-ask. Use the same packet and submit exactly one ballot with `t3_submit_output`.",
                    "",
                    brief,
                  ].join("\n"),
                  returns,
                  timeout: `${leftAgain} millis`,
                });
                problems = answer.outcome === "done" ? ballotProblems(p, routeSeat, answer.value) : [];
              }
            }
            const ended = yield* now(`${key}/ended`);
            const late = ended > deadline + GRACE_MS;
            if (answer.outcome === "done") {
              const status = late ? "late" : problems.length > 0 ? "invalid" : "valid";
              attempts.push({ route: requested(route), outcome: status, thread });
              return { seat, status, ballot: status === "valid" ? answer.value : null, problems: late ? ["the ballot came after the seat deadline"] : problems, requested: requested(route), reasked, thread, blind: true, attempts };
            }
            attempts.push({ route: requested(route), outcome: "failed", reason: answer.reason, thread });
            if (reaskable || late) {
              // The voter answered but never gave a ballot, or the deadline passed: the seat failed.
              return { seat, status: late ? "late" : "invalid", ballot: null, problems: [answer.reason], requested: requested(route), reasked, thread, blind: true, attempts };
            }
            // Could not start, died or timed out: try the next eligible route.
          }
          return { seat, status: "unavailable", ballot: null, problems: attempts.map((a) => a.reason ?? a.outcome), requested: null, reasked: false, thread: null, blind: true, attempts };
        });

      let seats;
      if (p.test?.ballots !== undefined) {
        seats = p.test.ballots.map((b) => {
          const status = b.status ?? "valid";
          const shaped = status === "valid" ? ballotProblems(p, b.seat, b) : [];
          return {
            seat: b.seat,
            status: shaped.length ? "invalid" : status,
            ballot: status === "valid" && !shaped.length ? b : null,
            problems: shaped,
            requested: null,
            reasked: false,
            thread: null,
            blind: true,
            attempts: [],
            synthetic: true,
          };
        });
      } else {
        const deadline = opened + limitMs;
        seats = yield* Effect.all(
          SEATS.map((seat) => {
            const inv = p.invokerSeat;
            if (inv !== undefined && inv.seat === seat) {
              return Effect.succeed({
                seat,
                status: "invoker-existing",
                ballot: { ...inv, model: "" },
                problems: [],
                requested: null,
                reasked: false,
                thread: p.invokerThread,
                blind: false,
                source: inv.source,
                attempts: [],
              });
            }
            return runSeat(seat, seat, seat, deadline);
          }),
          { concurrency: "unbounded" },
        );
        const unavailable = seats.filter((s) => s.status === "unavailable");
        if (unavailable.length === 1) {
          // One substitute, retried once; it gets its own deadline as a newly dispatched seat.
          const gone = unavailable[0];
          let sub = null;
          for (const attempt of [0, 1]) {
            const subOpened = yield* now(`clock/substitute/${attempt}`);
            sub = yield* runSeat("deepseek", "deepseek", `deepseek/${attempt}`, subOpened + limitMs);
            if (sub.status !== "unavailable") break;
          }
          seats = seats.map((s) => (s === gone ? { ...sub, substitutes: gone.seat, replaced: gone } : s));
        }
      }

      if (p.test?.pauseSeconds !== undefined) {
        // Test hook: pause the run before the tally so an operator can resume it.
        const armed = yield* now("test/armed");
        yield* T3.step(
          "test/pause",
          { returns: Schema.Number },
          Effect.suspend(() => {
            const wait = armed + p.test.pauseSeconds * 1000 - Date.now();
            return wait > 0
              ? Effect.fail(new Error(`test pause: resume after ${Math.ceil(wait / 1000)} more second(s)`))
              : Effect.succeed(Date.now());
          }),
        );
      }

      // Open votes: one judgment step groups equivalent ballots; code counts the groups.
      let groups = [];
      let grouping = null;
      const counted = seats.filter((s) => s.status === "valid" || s.status === "invoker-existing");
      if (p.kind === "open" && counted.length === 3) {
        const letters = LETTERS.slice(0, counted.length);
        const listed = counted.map((s, i) => `${letters[i]}. ${s.ballot.action.trim()}`).join("\n");
        const grouped = yield* T3.agent.try("group", {
          project,
          model: modelSelection(GROUPER),
          title: `vote grouping: ${p.question.slice(0, 60)}`,
          runtimeMode: RUNTIME_MODE,
          interactionMode: INTERACTION_MODE,
          timeout: "5 minutes",
          returns: Schema.Struct({ groups: Schema.Array(Schema.Array(Schema.String)), reasoning: Schema.String }),
          brief: [
            "Group these proposed actions. Use no tool except `t3_submit_output`.",
            "Two actions match only when the verb, the object and every material parameter agree,",
            "and neither omits or rules out a step the other has. A material parameter is any",
            "parameter either sentence states. Wording does not matter. If matching needs argument,",
            "or one action is a superset of another, they do not match.",
            "",
            `Question: ${p.question}`,
            "",
            listed,
            "",
            "Submit `groups`: every letter exactly once, matching letters together, for example [[\"A\",\"C\"],[\"B\"]].",
            "Submit `reasoning`: one line per group.",
          ].join("\n"),
        });
        const shapeProblems = grouped.outcome === "done" ? groupProblems(grouped.value.groups, letters) : [grouped.reason];
        if (shapeProblems.length === 0) {
          groups = grouped.value.groups;
          grouping = `${JSON.stringify(groups)} — ${grouped.value.reasoning}${grouped.thread ? ` (thread ${grouped.thread.threadId})` : ""}`;
        } else {
          grouping = `failed: ${shapeProblems.join("; ")}`;
        }
        const verdict = shapeProblems.length === 0
          ? tally(p, seats, groups)
          : { outcome: "incomplete", choice: null, reason: `open-vote grouping failed: ${shapeProblems.join("; ")}`, dependsOn: [], unverified: [] };
        const result = { run: id, test, packet: packetText(p, minutes), seats, grouping, tally: verdict };
        const told = yield* callback(resultText(p, result));
        return { ...result, callback: told.outcome === "done" ? "delivered" : `failed: ${told.reason}` };
      }

      const verdict = tally(p, seats, groups);
      const result = { run: id, test, packet: packetText(p, minutes), seats, grouping, tally: verdict };
      const told = yield* callback(resultText(p, result));
      return { ...result, callback: told.outcome === "done" ? "delivered" : `failed: ${told.reason}` };
    }),
);
