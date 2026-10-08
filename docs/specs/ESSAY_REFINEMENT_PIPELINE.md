# Essay Refinement Pipeline — Implementation Spec

**Status:** Proposed
**Author:** Armand / Cowork session 2026-03-31
**Goal:** Automate the process of turning a cluster of raw ideas into an adversarially tested, publishable essay — using Aragora's existing multi-model debate infrastructure.

---

## 1. The Problem

Writing a good essay currently requires manually copying ideas into multiple AI chatbots (Claude, ChatGPT, Gemini, Grok), pasting their feedback back and forth, synthesizing critiques by hand, and iterating manually. This is slow, lossy, and doesn't leverage the adversarial debate architecture Aragora already has.

## 2. What Exists Already

Aragora has everything needed at the infrastructure level:

| Capability | Location | Status |
|-----------|----------|--------|
| Multi-model orchestration (46 agent types) | `aragora/debate/orchestrator.py` | ✅ Stable |
| Propose → Critique → Revise → Vote loop | `aragora/debate/phases/` | ✅ Stable |
| Configurable debate protocol | `aragora/debate/protocol.py` | ✅ Stable |
| Workflow engine with loops & checkpoints | `aragora/workflow/engine.py` | ✅ Stable |
| Agent creation (`create_agent`) | `aragora/agents/base.py` | ✅ Stable |
| ELO ranking per domain | `aragora/ranking/elo.py` | ✅ Stable |
| Trickster (hollow consensus detection) | `aragora/debate/trickster.py` | ✅ Stable |
| Gauntlet adversarial testing | `aragora/gauntlet/orchestrator.py` | ✅ Stable |
| Cryptographic receipts | `aragora/gauntlet/receipt_models.py` | ✅ Stable |
| Knowledge Mound (cross-session learning) | `aragora/knowledge/` | ✅ Stable |

## 3. What Needs to Be Built

Three new components, one new CLI command, and one workflow definition.

### 3.1 Essay Evaluation Rubric (`aragora/essay/rubric.py`)

LLM-as-judge scoring for prose. Returns structured scores that plug into the existing vote/consensus system.

```python
@dataclass
class EssayScore:
    """Structured evaluation of an essay draft."""
    thesis_clarity: float       # 0-1: Is the central argument clear and stated early?
    argument_coherence: float   # 0-1: Do the sections build logically?
    evidence_grounding: float   # 0-1: Are claims backed by specifics, not vibes?
    rhetorical_force: float     # 0-1: Does it land? Is the closing strong?
    concision: float            # 0-1: Is every paragraph earning its place?
    factual_accuracy: float     # 0-1: Are verifiable claims correct?
    originality: float          # 0-1: Does it say something new or reframe something known?
    overall: float              # Weighted composite

    severity_notes: list[str]   # Specific issues (maps to Critique.severity)
    suggestions: list[str]      # Actionable improvements

async def evaluate_essay(
    essay_text: str,
    rubric_prompt: str,
    judge_agent: Agent,
    context: dict[str, Any] | None = None,  # Original idea cluster, prior drafts, etc.
) -> EssayScore:
    """
    Ask a judge agent to score an essay against the rubric.
    Returns structured EssayScore parsed from the agent's response.
    """
```

The rubric prompt should instruct the judge to:
- Score each dimension 0-1 with a one-sentence justification
- Identify the single weakest paragraph and explain why
- Identify the single strongest paragraph and explain why
- Flag any factual claims that need verification
- Return scores as JSON (parseable by the pipeline)

### 3.2 Essay-Specific Agent Roles (`aragora/essay/roles.py`)

Custom `RoundPhase` definitions for essay debate. Maps onto the existing phase system.

```python
ESSAY_ROUND_PHASES: list[RoundPhase] = [
    RoundPhase(
        number=0,
        name="Idea Extraction",
        description="Parse the raw idea cluster into core claims, tensions, and candidate thesis statements",
        focus="What are the 2-3 strongest ideas? What's the throughline?",
        cognitive_mode="Analyst",
    ),
    RoundPhase(
        number=1,
        name="Parallel Drafting",
        description="Each agent independently drafts the essay from the extracted thesis",
        focus="Structure, voice, opening hook, closing image",
        cognitive_mode="Writer",
    ),
    RoundPhase(
        number=2,
        name="Structural Critique",
        description="Challenge argument structure, logical gaps, unsupported claims",
        focus="Does the argument hold? Are there missing steps? Does the evidence earn the conclusion?",
        cognitive_mode="Skeptic",
    ),
    RoundPhase(
        number=3,
        name="Factual Audit",
        description="Verify every factual claim. Flag anything unverifiable or wrong.",
        focus="Named people, dates, products, studies, historical claims",
        cognitive_mode="Fact-Checker",
    ),
    RoundPhase(
        number=4,
        name="Devil's Advocate",
        description="Argue the strongest counter-position. What would a smart critic say?",
        focus="Steelman the opposition. Where is the essay most vulnerable?",
        cognitive_mode="Devil's Advocate",
    ),
    RoundPhase(
        number=5,
        name="Synthesis & Revision",
        description="Incorporate valid critiques. Merge strongest elements across drafts.",
        focus="Take the best structure, best paragraphs, best closing from all versions",
        cognitive_mode="Synthesizer",
    ),
    RoundPhase(
        number=6,
        name="Style Polish",
        description="Tighten prose. Cut filler. Strengthen verbs. Check tone consistency.",
        focus="Every sentence should earn its place. Remove anything that sounds like a chatbot.",
        cognitive_mode="Editor",
    ),
    RoundPhase(
        number=7,
        name="Final Judgment",
        description="Score the final draft against the rubric. Publish or iterate.",
        focus="Is this publishable? What score does it get? Does it need another round?",
        cognitive_mode="Judge",
    ),
]
```

### 3.3 Essay Synthesizer Step (`aragora/essay/synthesizer.py`)

This is the piece that doesn't exist in Aragora. Current merge is git-based (code). Essay merge is semantic — take the best structural move from Draft A, the best paragraph from Draft B, the strongest opening from Draft C.

```python
class EssaySynthesizerStep:
    """
    Workflow step that takes multiple essay drafts + critiques
    and produces a merged revision.

    Uses a dedicated synthesizer agent with a prompt that includes:
    - All drafts (numbered)
    - All critique scores (per rubric dimension)
    - Specific instructions: "Take the structure from Draft X,
      the opening from Draft Y, and rewrite the weakest section
      identified in the critiques"
    """

    async def execute(self, context: WorkflowContext) -> str:
        drafts = context.get_state("drafts")           # list[str]
        scores = context.get_state("scores")            # list[EssayScore]
        critiques = context.get_state("critiques")      # list[str]

        # Rank drafts by overall score
        ranked = sorted(zip(drafts, scores), key=lambda x: x[1].overall, reverse=True)

        # Build synthesis prompt
        prompt = build_synthesis_prompt(
            ranked_drafts=ranked,
            critiques=critiques,
            target_word_count=context.get_config("target_words", 1200),
            voice_notes=context.get_config("voice_notes", ""),
        )

        # Use the highest-ELO synthesizer agent
        result = await self.synthesizer_agent.generate(prompt)
        return result.text
```

### 3.4 CLI Command (`aragora/cli/commands/essay.py`)

```
aragora essay refine --input ideas.md --target-words 1200 --rounds 3 --output essay.md
aragora essay refine --input ideas.md --dry-run          # Show extracted thesis + outline only
aragora essay refine --input ideas.md --resume <id>      # Resume from checkpoint
aragora essay score --input draft.md                      # Score an existing draft against rubric
```

Flags:
- `--input`: Raw idea cluster (markdown, text, or conversation transcript)
- `--target-words`: Target length (default 1200)
- `--rounds`: Number of refine-critique-revise iterations (default 3)
- `--models`: Comma-separated model list (default: anthropic,openai,gemini)
- `--voice-notes`: Style guidance ("conversational Substack tone, no bullet points")
- `--output`: Output file path
- `--dry-run`: Extract thesis and outline without drafting
- `--resume`: Resume from checkpoint ID
- `--rubric`: Path to custom rubric YAML (optional)

## 4. Pipeline Architecture

```
┌─────────────────────────────────────────────────────┐
│                    INPUT                             │
│  Raw idea cluster (conversation, notes, fragments)  │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  PHASE 0: Idea Extraction (1 debate round)          │
│  • Parse raw input into core claims & tensions      │
│  • Identify candidate thesis statements             │
│  • Agents vote on strongest thesis + structure       │
│  Output: thesis statement + outline                  │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  PHASE 1: Parallel Drafting                          │
│  • Each model writes a complete draft independently  │
│  • All given same thesis + outline                   │
│  • 3-4 independent drafts produced                   │
│  Output: list[draft]                                 │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  PHASE 2: Evaluation + Critique                      │
│  • Each draft scored against rubric (all judges)     │
│  • Structural critique from each model               │
│  • Factual audit (web search for verifiable claims)  │
│  • Trickster checks for hollow consensus / groupthink│
│  Output: list[EssayScore] + list[critique]           │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  PHASE 3: Synthesis                                  │
│  • Merge best elements from top-ranked drafts        │
│  • Incorporate specific critique suggestions          │
│  • Rewrite weakest sections identified by judges     │
│  Output: merged_draft                                │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
              ┌────────┴────────┐
              │  Score > 0.8?   │──── YES ──→ PHASE 5: Polish
              └────────┬────────┘
                       │ NO
                       ▼
              ┌────────────────┐
              │ Rounds left?   │──── NO ──→ PHASE 5: Polish (best available)
              └────────┬───────┘
                       │ YES
                       ▼
              Loop back to PHASE 2 with merged_draft as new input
              (each subsequent round also receives prior critique history)

┌─────────────────────────────────────────────────────┐
│  PHASE 5: Final Polish                               │
│  • Style edit pass (cut filler, tighten verbs)       │
│  • Tone consistency check                            │
│  • Word count adjustment                             │
│  • Final rubric score + receipt generation            │
│  Output: final_essay + receipt                       │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
                  Save to --output
                  Print final score + summary
```

## 5. Workflow Definition (YAML)

This plugs into the existing `WorkflowEngine`:

```yaml
id: essay-refinement-v1
name: "Essay Refinement Pipeline"
description: "Transform raw ideas into publishable essays via adversarial debate"

steps:
  - id: extract_ideas
    type: debate
    config:
      task_template: |
        Extract the core claims, tensions, and candidate thesis statements
        from this raw idea cluster. Identify the single strongest thesis
        and propose a 4-6 section outline for a {target_words}-word essay.

        Raw ideas:
        {input_text}
      rounds: 1
      consensus: majority

  - id: parallel_draft
    type: parallel
    config:
      fan_out_to: [anthropic, openai, gemini]
      task_template: |
        Write a complete {target_words}-word essay based on this thesis and outline.
        Voice: {voice_notes}

        Thesis: {extract_ideas.thesis}
        Outline: {extract_ideas.outline}

  - id: evaluate_and_critique
    type: debate
    config:
      task_template: |
        Score each draft against this rubric and provide structural critique.
        Identify the strongest and weakest elements of each.
        {rubric}

        Drafts:
        {parallel_draft.outputs}
      rounds: 1

  - id: synthesize
    type: agent
    config:
      agent: best_available_synthesizer
      task_template: |
        Merge the best elements from these drafts based on the scores
        and critiques. Produce a single {target_words}-word essay.
        {synthesis_instructions}

  - id: refine_loop
    type: loop
    config:
      max_iterations: "{rounds}"
      exit_condition: "state.latest_score.overall > 0.8"
      steps:
        - id: re_critique
          type: debate
          config:
            task_template: |
              Score this revised draft against the rubric.
              Focus especially on whether previous critique issues were addressed.
              {rubric}

              Previous issues: {state.previous_critiques}
              Current draft: {state.current_draft}
        - id: re_synthesize
          type: agent
          config:
            task_template: |
              Revise this draft based on the new critiques.
              Preserve what's working. Fix what isn't.

              Draft: {state.current_draft}
              Critiques: {re_critique.output}

  - id: polish
    type: agent
    config:
      agent: style_editor
      task_template: |
        Final polish. Tighten every sentence. Cut filler words.
        Ensure the opening hooks and the closing lands.
        Check word count is within 10% of {target_words}.
        Do not change the argument structure.

        Draft: {state.current_draft}

  - id: final_score
    type: agent
    config:
      agent: judge
      task_template: |
        Score this final essay against the full rubric.
        Return JSON scores only.
        {rubric}

        Essay: {polish.output}
```

## 6. File Structure

```
aragora/essay/
├── __init__.py
├── rubric.py            # EssayScore dataclass + evaluate_essay()
├── roles.py             # ESSAY_ROUND_PHASES
├── synthesizer.py       # EssaySynthesizerStep
├── prompts.py           # All prompt templates (extraction, drafting, critique, synthesis, polish)
├── pipeline.py          # EssayRefinementPipeline class (orchestrates the full workflow)
└── cli.py               # CLI entry point (registered in aragora/cli/commands/)

aragora/essay/rubrics/
├── default.yaml         # Default essay rubric
├── substack.yaml        # Substack-optimized (shorter, punchier, conversational)
├── academic.yaml        # Academic (more evidence weight, less rhetorical force)
└── technical.yaml       # Technical blog (clarity + accuracy weighted heavily)

docs/specs/
└── ESSAY_REFINEMENT_PIPELINE.md   # This document

tests/essay/
├── test_rubric.py
├── test_synthesizer.py
├── test_pipeline.py
└── test_cli.py
```

## 7. Agent Configuration for Essays

Recommended model assignments (configurable):

| Role | Recommended Model | Why |
|------|------------------|-----|
| Drafter | Claude Opus / Sonnet | Best prose quality |
| Drafter | GPT-4o | Different structural instincts |
| Drafter | Gemini 2.0 Pro | Good at factual grounding |
| Structural Critic | Claude Opus | Best at identifying logical gaps |
| Fact Checker | GPT-4o + web search | Tool use for verification |
| Devil's Advocate | Grok | Contrarian by design |
| Style Editor | Claude Sonnet | Clean, concise prose |
| Synthesizer | Claude Opus | Best at integrating complex inputs |
| Final Judge | Different model from synthesizer | Avoids self-evaluation bias |

## 8. Key Design Decisions

**Why not just run a standard Arena debate on "write an essay"?**

The standard debate protocol optimizes for *consensus on a decision*. Essay writing requires a different loop: parallel *creation*, then selective *merging*, then iterative *refinement*. The propose-critique-revise pattern is right, but the propose step needs to produce full drafts (not positions), the critique step needs prose-specific rubrics (not logical arguments), and the synthesis step needs semantic merging (not vote aggregation).

**Why separate extraction from drafting?**

If you give raw conversation transcripts directly to drafters, each model will pick a different thesis. The extraction phase forces consensus on *what the essay is about* before anyone writes, which means the drafts are comparable and mergeable.

**Why a quality gate (score > 0.8) instead of fixed rounds?**

Some essays converge fast (the ideas are already clean). Some need more work. A fixed round count either wastes API calls on good drafts or underprocesses weak ones. The quality gate + max rounds cap gives you both efficiency and a safety net.

**Why use the Trickster?**

Without it, models tend toward consensus too quickly — they all agree the draft is "good" without substantive critique. The Trickster detects when critiques lack specific, actionable feedback and injects challenge prompts. This is especially important for prose, where models default to polite praise.

## 9. Implementation Order

1. **`aragora/essay/rubric.py`** — Get scoring working first. This is the foundation everything else depends on.
2. **`aragora/essay/prompts.py`** — All prompt templates in one place, testable independently.
3. **`aragora/essay/roles.py`** — Essay-specific round phases.
4. **`aragora/essay/synthesizer.py`** — The novel component. Needs careful prompt engineering.
5. **`aragora/essay/pipeline.py`** — Wire it all together using WorkflowEngine.
6. **`aragora/essay/cli.py`** — CLI entry point.
7. **Tests** — Unit tests for rubric parsing, integration tests for full pipeline with mock agents.
8. **Rubric YAML files** — Start with `substack.yaml` since that's the immediate use case.

## 10. Future Extensions

- **Voice/style transfer**: Analyze a corpus of the user's published writing, extract style patterns, add as constraint to drafting prompts.
- **Fact-checking with web search**: Integrate Aragora's existing web search capabilities into the factual audit phase.
- **Receipt publishing**: Generate a "debate receipt" showing how the essay was refined, publishable as a companion piece (meta-content about the process).
- **Idea clustering**: Pre-pipeline step that takes unstructured notes/conversations from multiple sources and clusters them into essay-ready idea packets.
- **Autonovel integration**: Scale the same pipeline for longer-form writing (chapters, reports) using the loop-and-checkpoint pattern.
- **ELO tracking per writing domain**: Track which models are best at which kinds of essays over time.
