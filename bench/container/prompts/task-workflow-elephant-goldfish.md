Check the document {SCENARIO_DIR}/incorrect.md against its source {SCENARIO_DIR}/source.md. Use a factual check and a cold read. The cold reader receives only the document and the source, never your findings or this task's objective; {SCENARIO_DIR}/cold-brief-template.md is the cold brief format. The scope is in {SCENARIO_DIR}/input.json.

Write these files into {SCENARIO_DIR}: cold-brief.md (the exact brief the cold reader received), corrections.json (one row per incorrect statement, with the source value, citing source.md and its SHA-256), and observation.json.
