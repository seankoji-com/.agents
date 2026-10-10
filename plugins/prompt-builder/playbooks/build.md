# Build a prompt

1. Establish the task, consumer, target model, input shape, required output, constraints,
   tool access, and failure examples. Inspect discoverable facts yourself. Batch only
   questions whose answers change the prompt. For brief-only, return these fields and stop.
2. Draft the shortest plausible baseline. State the task and output contract plainly.
   Separate trusted instructions from supplied data. Use examples for ambiguous rules;
   include a difficult boundary example. Use placeholders with definitions and defaults.
   Ask for concise rationale or checkable evidence, not hidden chain-of-thought.
3. Critique ambiguity, missing context, conflicting instructions, and injection from
   inputs or tool output. Choose a candidate only when it addresses a concrete failure.
   Split into stages only when the stages have independently checkable outputs.
4. Freeze normal, edge, and adversarial cases before comparing. Keep one case held out
   during revision. Use `PKG/references/evaluation.md` for the saved-evidence format.
   Execute baseline and candidate in fresh contexts with identical model, settings,
   tools, and inputs. Executors must not see expected answers. Use isolated tool fixtures.
   Use available T3 delegation only when authorized; otherwise save a runnable suite
   and report `evaluation: not_run`. Never invent outputs to fill the comparison.
5. Run the deterministic evaluator. Prefer a fully passing baseline unless the
   candidate repairs a failure or is shorter with the same passes. Subjective criteria
   also need a blind rubric-based assessment. Stop after two revision rounds.
6. Deliver the exact prompt, variable definitions, invocation example, intended model,
   test cases, measured results, and limitations. Save where the operator requested.
   Do not automatically append to personal memory or commit/push a dotfiles repository.
