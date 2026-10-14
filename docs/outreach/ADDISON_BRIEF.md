# Addison Applications — Aragora Assignment Brief

**Client:** Synaptent (Armand Tuzel)
**Project:** Aragora — aragora.ai
**Budget:** Part of existing $3k/mo retainer
**Timeline:** 2-3 weeks for initial delivery

---

## What Aragora Is

Aragora is an AI decision integrity platform. It orchestrates multiple AI models (Claude, GPT-4, Gemini, Mistral, Grok) to debate decisions adversarially, then produces cryptographic receipts proving what was decided, by whom, and with what confidence. Think "audit trail for AI-assisted decisions."

The backend API is live at **api.aragora.ai**. The frontend is a Next.js app deployed on Vercel at **aragora.ai**.

---

## What We Need From Addison

### Scope: Marketing/Signup Conversion Flow

Build a polished user journey from "what is this?" to "I'm trying it" on aragora.ai.

**Pages to build or polish:**

1. **Landing page** (`/landing/`)
   - Hero with clear value prop and CTA
   - "Try a Demo" button that runs a real debate (API endpoint exists and works)
   - Social proof section (when available)
   - How it works (3-step visual)
   - Use copy from `docs/outreach/DESIGN_PARTNER_ONEPAGER.md` in the repo

2. **Pricing page** (`/pricing/`)
   - 3 tiers: Starter ($49/mo), Professional ($149/mo), Enterprise (custom)
   - Feature comparison table
   - CTA to Stripe checkout (we'll provide the Stripe integration)
   - Use structure from `docs/strategy/PRICING_HYPOTHESES.md`

3. **Signup/onboarding flow** (`/signup/` → `/get-started/`)
   - Clean signup form (email + password, or SSO)
   - 3-step onboarding wizard already exists at `/get-started/` — polish the design
   - Ensure mobile responsiveness

4. **Demo result page** (`/demo/`)
   - Already functional — needs design polish
   - Agent cards showing each AI's position
   - Verdict section with confidence score
   - Receipt hash for audit trail

### Design Direction

- **Current design system:** Tailwind CSS, Next.js App Router, CSS custom properties for theming
- **3 themes exist:** Dark (terminal/hacker), Warm (light), Professional (clean, green accents)
- **Professional theme** should be the default for marketing pages
- **Brand color:** `#16a34a` (Tailwind green-600)
- **Fonts:** Inter for UI, JetBrains Mono for code/data
- **Tone:** Professional but not corporate. Think Stripe or Linear, not enterprise software.

### What NOT to Touch

- Python backend (aragora/ directory)
- API endpoints
- Debate engine logic
- DevOps/deployment (handled by CI/CD)

---

## Technical Context

| Item | Detail |
|------|--------|
| **Stack** | Next.js 14, TypeScript, Tailwind CSS v4 |
| **Hosting** | Vercel (auto-deploys from GitHub `main` branch) |
| **API** | api.aragora.ai (Python/FastAPI, deployed on EC2) |
| **Repo** | github.com/synaptent/aragora |
| **Frontend dir** | `aragora/live/` |
| **Design tokens** | `aragora/live/src/app/globals.css` (CSS custom properties) |
| **Components** | `aragora/live/src/components/` |
| **Content source** | `docs/outreach/` and `docs/strategy/` |

### Key API Endpoints (already working)

- `GET /api/v1/health` — health check
- `POST /api/v1/playground/debate` — run a debate (no auth required for demo)
- `GET /api/v1/debates` — list past debates
- `POST /api/v1/api-keys` — create API key
- `GET /api/v1/public/surfaces` — list available public features

### Content Already Written

All marketing copy has been drafted in the repo:

- `docs/outreach/DESIGN_PARTNER_ONEPAGER.md` — main value prop and proof points
- `docs/outreach/BUYER_ANALYST_FAQ.md` — FAQ content
- `docs/outreach/FOUNDER_PROOF_POINTS_LIBRARY.md` — evidence claims
- `docs/strategy/BOUNDARIES_AND_SCOPE.md` Part 1 — what Aragora is NOT (absorbed `NON_GOALS_LEDGER.md`)
- `docs/strategy/PRECISION_AND_TERMS.md` Part 1 — product terminology (absorbed `TERMINOLOGY_GLOSSARY.md`; see `docs/strategy/STRATEGY_INDEX.md`)

---

## Deliverables

1. Polished landing page with working demo CTA
2. Pricing page with tier comparison
3. Signup flow that connects to existing auth backend
4. Mobile-responsive across all pages
5. Consistent with Professional theme design tokens

## Success Criteria

- A stranger can visit aragora.ai, understand what it does in 10 seconds, run a demo debate, and sign up — without needing to read documentation.
- Lighthouse score > 90 on performance and accessibility.
- All pages work on mobile.

---

## Getting Started

1. Clone the repo: `git clone https://github.com/synaptent/aragora.git`
2. Frontend is in `aragora/live/`
3. Run locally: `cd aragora/live && npm install && npm run dev`
4. The Professional theme activates via the theme selector (top-right moon icon → click until "Pro" appears)
5. Read `docs/outreach/DESIGN_PARTNER_ONEPAGER.md` for copy direction

Questions? Reach out to Armand directly.
