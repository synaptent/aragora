# H2 Partial Multi-Seeded Judge Contract Note

Date: 2026-05-04

## Context

Round 31b H2 compared the landed single-family Anthropic baseline against a
fallback-aware heterogeneous panel. The comparator result was mechanically
`NO-GO` under strict CI separation, but the operator-facing settlement position
was downgraded to `INSUFFICIENT-WITH-DATA` after transcript review found an
underspecified judge contract for `multi_seeded_error` prompts.

The ambiguous case is a response that catches one seeded error in a prompt that
contains multiple seeded errors. The previous judge prompt used singular wording:
"the seeded error." The judge could reasonably interpret a partial catch as a
miss because it did not catch every seeded error, but that behavior was not
explicitly specified.

## Contract Repair

The judge contract now makes the multi-seeded case explicit:

- `flagged_correctly`: names every seeded error, or a strict superset that
  includes every seeded error plus additional legitimate strict issues.
- `partial_multi_seeded`: names a strict non-empty subset of seeded errors, but
  not all of them.
- `missed`: names none of the seeded errors.
- `flagged_wrongly`: flags an error that is not present and not seeded.

`partial_multi_seeded` is a separate metric signal. It is not silently counted as
`independent_flag_successes`, so existing comparator verdict behavior remains
stable unless a future methodology PR explicitly changes the verdict rule.

## Non-Claims

This contract repair does not re-judge prior receipts, does not regenerate the
baseline, does not change the comparator verdict rule, does not settle H2, and
does not close #6375. A corrected H2 verdict requires symmetric re-judging or
regeneration under this amended contract.
