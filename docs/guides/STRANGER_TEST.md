# The Stranger Test

A copy-paste kit for getting cold-eyes feedback on Aragora from a developer
friend with zero context. Send them everything below the line.

---

## The ask (send this verbatim)

> I want 15 minutes of your time and your honest first impressions of a
> project I work on. Run the commands below, time each step, and tell me
> exactly where you got stuck, confused, or bored — the negative feedback is
> the valuable part.

## The commands

```bash
pip install aragora
aragora demo --offline
aragora verify aragora-demo-receipt.json
```

No API keys, no accounts, no config. The demo runs a self-contained
adversarial debate with mock agents and writes a decision receipt to your
current directory; `verify` checks that receipt's integrity.

## What to observe (while it runs)

- **Time each step.** Install time, demo runtime, verify runtime. Note
  anything that felt slow.
- **Note every confusion.** Every moment you weren't sure what was happening,
  what a word meant, or whether something had worked — write it down, however
  small. "I didn't know what a receipt was" is exactly the kind of note we need.
- **Note where you stopped reading.** Output, README, anything.

## Debrief (5 questions)

1. Where did you stop reading, and why?
2. What did you think this product *was*, before and after running it?
3. Would you trust the receipt? Why or why not?
4. What's missing before you'd actually use this for something real?
5. Who do you know who needs this?

## What happens to your feedback

Every point of friction you report becomes a GitHub issue at
[synaptent/aragora](https://github.com/synaptent/aragora/issues) — your
confusion is treated as a bug in the product, not a gap in your reading.
Thank you.
