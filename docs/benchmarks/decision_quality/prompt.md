# Outcome-Backed Decision Quality Prompt Contract v1

You are making a bounded decision using only the case packet supplied with
this prompt. The packet contains an information cutoff and pre-cutoff source
metadata. Do not use later knowledge, web searches, hidden outcomes, or facts
from another benchmark case.

Choose exactly one of the two option IDs. Report a probability from 0 through
1 for the case's `forecast_option_id`, even when you select the other option.
Identify the three to five uncertainties that most affect the choice. Cite
only `source_id` values present in this case packet. State limitations rather
than inventing missing evidence.

Return one JSON object with exactly these fields:

```json
{
  "selected_option_id": "one supplied option_id",
  "forecast_probability": 0.5,
  "cruxes": ["bounded decision-relevant uncertainty"],
  "source_ids": ["one supplied source_id"],
  "rationale": "concise reasoning grounded in the supplied packet"
}
```

For the `aragora_team` condition, the same three model families first produce
independent answers, perform one bounded adversarial critique round, and then
the declared synthesizer emits the same JSON shape. No member may receive an
outcome sidecar or another benchmark case. The runner must emit a verifiable
DecisionReceipt for the synthesized result.
