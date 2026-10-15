# Provider compatibility

imps promises identical workflow rules, artifact formats and completion criteria on every tested provider. It does not promise identical judgment, code quality, latency or native tool features.

The live results, with the T3 version, the provider and model IDs, every repeat's artifacts and each status (`verified`, `partial`, `unavailable`, `not tested`), are kept in the source repository under `conformance/`: `compatibility.json`, `compatibility.md` and `results/`. A provider is `verified` only when every critical live case passed three out of three repeats with no intervention and no false completion. An advertised model is not a verified one.

To rerun the procedure from a T3 thread, follow `conformance/procedure.md` in the source repository.

## Doctor identity reporting

Doctor reports identity information from saved host observations only. Name every
provider with a recorded unreported-model observation, and list providers without
a recorded identity result as `identity reporting unverified`. Do not infer identity
from configured targets or query the live provider catalog. Launch nothing to fill
an observation gap.

Those dated observations used the previous major-version-1 gate. The smaller gate
has deterministic regression coverage; live provider compatibility has not yet been
observed. Activate the previous package to reproduce the historical procedure.
