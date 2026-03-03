# EU AI Act Compliance Package — Ship Design

**Date:** 2026-03-03
**Status:** In Progress
**Goal:** Make the EU AI Act compliance tools accessible, demoable, and connected to the debate flow

---

## Current State

- Backend: Complete (7,027 LOC, 3 API endpoints, CLI, SDK, 200+ tests)
- Dashboard: Complete at `(app)/compliance/page.tsx` (requires auth, hacker theme only)
- Documentation: Complete (4 guides)
- Gap: No public-facing demo, no post-debate integration, no tri-theme support

## Implementation Plan

### 1. Standalone Public Compliance Page

Create `(standalone)/compliance/page.tsx` — a focused EU AI Act page accessible without auth.

**Sections:**
- Hero: "EU AI Act Compliance in One Click" + deadline countdown (Aug 2, 2026)
- Risk Classifier: Input AI use-case description → get risk level (reuse existing demo fallback)
- Bundle Preview: Show what a compliance bundle looks like (Articles 12/13/14)
- CTA: "Run a debate to generate a real bundle" → links to Oracle

**Styling:** Uses tri-theme CSS variables (warm/dark/pro) matching landing page.

### 2. Post-Debate Compliance CTA

After Oracle debate completes, show a "Generate EU AI Act Bundle" button.
- Uses the actual debate receipt data (not demo data)
- Links to compliance page with receipt pre-loaded via URL params or sessionStorage

### 3. Landing Page Link

Add "Compliance" to the landing page header nav, linking to the standalone compliance page.

### 4. Theme Updates

Update the existing `(app)/compliance/page.tsx` to use `var(--accent)` instead of hardcoded `var(--acid-green)`, and conditionally show CRT/scanline effects only in dark theme.

---

## Files to Create/Modify

- CREATE: `aragora/live/src/app/(standalone)/compliance/page.tsx`
- MODIFY: `aragora/live/src/components/Oracle.tsx` — add post-debate CTA
- MODIFY: `aragora/live/src/components/landing/Header.tsx` — add Compliance nav link
