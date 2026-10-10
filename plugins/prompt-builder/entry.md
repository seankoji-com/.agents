# prompt-builder

Build and evaluate a reusable prompt. Do not execute the prompt's underlying task.
Read `PKG/shared/t3-runtime.md`, then `PKG/playbooks/build.md`.

- `build <brief>`: diagnose, draft, critique, and deliver a reusable prompt.
- `brief-only <brief>`: return only a structured brief; do not save files or evaluate.
- `evaluate <suite> <baseline> <candidate>`: run
  `python3 PKG/scripts/evaluate.py <suite> <baseline> <candidate>` on saved evidence.
- `doctor`: check Python 3.10+ and that the evaluator's `--help` runs. No model call.

Choose prompt syntax for the user's target model. Do not assume Claude, prescribe a
fixed provider, or claim an improvement without comparable evaluation results.
