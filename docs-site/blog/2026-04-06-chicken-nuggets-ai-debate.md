---
slug: chicken-nuggets-ai-debate
title: I Asked 3 AI Models If I Should Microwave My Chickens
authors: [armand]
tags: [product, ai-debate, disambiguation]
description: What happens when you ask an ambiguous question to multiple AI models debating each other? A chicken nuggets story that reveals why single-model AI fails.
---

# I Asked 3 AI Models If I Should Microwave My Chickens

My 4-year-old wanted chicken nuggets. I typed "should I cook my chickens in a microwave? what if they are alive, and what if they are dead" into Aragora's landing page and hit Start Debate.

Three AI models — Claude, GPT, and Grok — spent 10 seconds earnestly debating whether it's legal to microwave live animals.

<!-- truncate -->

## What Happened

I got a 3-paragraph ethics lecture from GPT about animal cruelty law. Claude produced a "Strategic Assessment: Chicken Cooking Method" with a "Competitive Positioning of Microwave vs. Alternatives" section. Grok gave me a step-by-step implementation plan for cooking dead chickens at 50% power.

None of them asked the obvious question: _are you just reheating nuggets for your kid?_

## Why This Matters

This isn't a story about AI being dumb. Each model's response was technically correct, well-reasoned, and thorough. The problem is that all three latched onto the most _interesting_ interpretation of an ambiguous question instead of the most _likely_ one.

A single AI model does the same thing — you just don't notice because there's nothing to compare it to. When three models independently make the same mistake, the pattern becomes visible: **AI models are biased toward philosophical depth over practical utility.**

There's nothing to debate about "microwave the nuggets for 2 minutes." The models gravitated to the ethical dimension because that's where the _debate_ is. They correctly identified the interesting question. They just incorrectly assumed that's the question I needed answered.

## The Fix: Real Intelligence, Not Regex

Our first attempt at fixing this was embarrassing. We built a regex-based disambiguation system that checked for keywords like `/\bmicrowave|reheat/` and `/\bchicken|nugget/`. It included a hardcoded chicken-nuggets detector.

This is exactly the wrong approach. You can't enumerate every ambiguous question a human might ask. The regex caught "microwave + chicken + alive/dead" but would miss "should I put my cats in the dryer" or a thousand other ambiguous questions.

So we replaced it with what we should have done from the start: **we ask a frontier AI model whether the question is clear or ambiguous.** Before the debate runs, a fast model (Claude Sonnet) reads your question and decides:

- **Clear?** Go straight to debate. Zero friction.
- **Ambiguous?** Show you 2-3 interpretations and let you pick.

For the chicken nuggets question, it now shows:

> _This question could mean a few things:_
>
> 1. Is it safe to reheat pre-cooked chicken nuggets in a microwave?
> 2. What are the ethical considerations of factory-farmed chicken?
> 3. How should I cook raw chicken safely?

You pick #1, and 10 seconds later you get: "Yes, reheating pre-cooked chicken nuggets in a microwave is safe. Use 50% power, 2-3 minute intervals, check internal temp reaches 165F."

## The Deeper Point

My 4-year-old doesn't care about the ethics of factory farming. Neither did I, in that moment. But the models were right that the ethical dimension exists — I _am_ feeding my kid ground-up dead chickens, and I _did_ outsource the killing and grinding to a factory somewhere.

The question had both a trivial practical answer and a genuine philosophical dimension. The old system pretended only the philosophical one existed. The new system surfaces both and lets you choose.

That's what multi-model debate is actually for: not just getting the right answer, but making sure you're asking the right question.

## Try It

Go to [aragora.ai](https://aragora.ai) and ask something ambiguous. Watch what happens when three AI models check each other's work.

No signup required. No API keys needed. First verdict in under a minute.
