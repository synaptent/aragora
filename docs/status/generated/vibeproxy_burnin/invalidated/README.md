# Invalidated VibeProxy Burn-In Cohorts

These cohorts are retained as append-only audit history but MUST NOT be used
as proof toward issue #9409.

The exact-head Claude and OpenAI review of PR #9545 found that the recorder
could accept an opaque response model by inheriting the requested alias's
provider ownership. The affected records predate the fail-closed repair and
their generated `latest.json` summaries are historical outputs, not valid
current proof.

A replacement cohort must start after the repair lands. It must independently
verify the observed response model's family and retain the original thresholds:
7 days, 100 clean calls, 3 provider families, zero credential or identity
errors, and 20 non-countable shadow reviews.
