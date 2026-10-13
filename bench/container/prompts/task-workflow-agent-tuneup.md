Audit the synthetic provider settings file at {SETTINGS_PATH} and apply only the change that {SCENARIO_DIR}/input.json allowlists. Back up the original bytes first. Verify that the edited settings parse, load and enforce the change.

Write these files into {SCENARIO_DIR}: backup.bin (the original settings bytes), settings-after.json (the edited settings), and host-observation.json.
