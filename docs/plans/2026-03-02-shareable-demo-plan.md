# Viral-Shareable Debate Experience — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable visitors to run a debate on `/try`, share a permalink, and have recipients see the full debate + run their own — creating a see→try→share viral loop.

**Architecture:** The backend already persists debates and returns `share_url`. The standalone `/debate/[id]` route exists with `generateMetadata()`. We need to: (1) wire `share_url` through the try page to TeaserResult, (2) add share/copy UI, (3) make the standalone viewer fetch and render saved debates, (4) enrich OG metadata with debate content, (5) add "Run your own" CTA.

**Tech Stack:** Next.js 16 (RSC + `next/og`), TypeScript, Python backend (unchanged)

---

### Task 1: Pass debate response data through try page to TeaserResult

**Files:**
- Modify: `live/src/app/try/page.tsx`
- Modify: `live/src/components/try/TeaserResult.tsx`

**Step 1: Update TeaserResult props interface**

In `live/src/components/try/TeaserResult.tsx`, extend the props:

```tsx
interface TeaserResultProps {
  verdict: string;
  confidence: number;
  explanation: string;
  debateId?: string;
  shareUrl?: string;
  topic?: string;
  participants?: string[];
  proposals?: Record<string, string>;
}
```

**Step 2: Update try/page.tsx to store full response and pass to TeaserResult**

In `live/src/app/try/page.tsx`, the state currently stores `{verdict, confidence, explanation}`. Extend to also store `debateId`, `shareUrl`, `topic`, `participants`, `proposals` from the API response. Pass these as props to `<TeaserResult>`.

**Step 3: Run dev server and verify props flow**

Run: `cd live && npm run dev`
Test: Submit a question on `/try`, inspect React devtools to confirm new props arrive on TeaserResult.

**Step 4: Commit**

```bash
git add live/src/app/try/page.tsx live/src/components/try/TeaserResult.tsx
git commit -m "feat: pass full debate response through to TeaserResult"
```

---

### Task 2: Replace lock overlay with real debate content and share button

**Files:**
- Modify: `live/src/components/try/TeaserResult.tsx`

**Step 1: Replace the three locked sections with real content**

Replace the opaque locked sections (SHA-256 receipt, full transcript, shareable link) with:
- **Agent summary**: Show 2-3 agent names + first ~100 chars of their positions (from `participants` + `proposals`)
- **Share button**: When `shareUrl` is present, show a "SHARE THIS DEBATE" button that copies the full permalink to clipboard using `navigator.clipboard.writeText()`. Use `navigator.share()` where available (mobile), fall back to clipboard.
- **Keep the CTA**: Preserve "GET FULL RECEIPTS — START FREE" at the bottom

The share URL should be: `${window.location.origin}/debate/${debateId}`

```tsx
// Share button logic
const handleShare = async () => {
  const url = `${window.location.origin}/debate/${debateId}`;
  const text = `I stress-tested "${topic}" with AI agents on Aragora. Here's what they decided:`;

  if (navigator.share) {
    await navigator.share({ title: topic, text, url });
  } else {
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }
};
```

**Step 2: Test manually**

Run: `cd live && npm run dev`
Test: Submit question → verify agent summaries appear → click share → verify URL copied to clipboard.

**Step 3: Commit**

```bash
git add live/src/components/try/TeaserResult.tsx
git commit -m "feat: unlock teaser result with agent content and share button"
```

---

### Task 3: Make standalone debate viewer fetch and render saved debates

**Files:**
- Modify: `live/src/app/(standalone)/debate/[[...id]]/page.tsx`
- Modify: `live/src/app/(standalone)/debate/[[...id]]/DebateViewerWrapper.tsx`

**Step 1: Add server-side data fetching to page.tsx**

The `page.tsx` is already an RSC with `generateMetadata()`. Add a `fetchDebate()` helper that calls `GET /api/v1/playground/debate/{id}` server-side and pass the data as a prop to `DebateViewerWrapper`.

```tsx
async function fetchDebate(debateId: string) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
  try {
    const res = await fetch(`${apiUrl}/api/v1/playground/debate/${debateId}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}
```

**Step 2: Update DebateViewerWrapper to render saved debate data**

Currently the wrapper shows "NO DEBATE ID PROVIDED" when accessed directly. Add a `savedDebate` prop that, when present, renders the debate content using the same styling as the existing debate viewer but in read-only mode. Display:
- Topic as header
- Agent cards with their proposals (first 500 chars each)
- Vote breakdown
- Final verdict with confidence
- "Run your own debate" CTA linking to `/try?topic=<encoded_topic>`

**Step 3: Handle error states**

- Debate not found → show `not-found.tsx` (already exists)
- Debate in progress → show "Debate still running" message
- Debate failed → show error + CTA to try again

**Step 4: Test manually**

Run dev server, submit a debate on `/try`, note the debate ID from the response, visit `/debate/{id}` directly → should render full debate.

**Step 5: Commit**

```bash
git add live/src/app/'(standalone)'/debate/
git commit -m "feat: standalone debate viewer fetches and renders saved debates"
```

---

### Task 4: Enrich OpenGraph metadata with debate content

**Files:**
- Modify: `live/src/app/(standalone)/debate/[[...id]]/page.tsx`

**Step 1: Enhance generateMetadata() to fetch debate data**

Use the same `fetchDebate()` helper to populate OG tags with real content:

```tsx
export async function generateMetadata(props: { params: Promise<{ id?: string[] }> }): Promise<Metadata> {
  const params = await props.params;
  const debateId = params.id?.[0];
  if (!debateId) {
    return { title: 'ARAGORA Debate Viewer' };
  }

  const debate = await fetchDebate(debateId);
  const topic = debate?.topic || `Debate ${debateId.slice(0, 12)}`;
  const verdict = debate?.verdict || 'Analysis Complete';
  const confidence = debate?.confidence ? `${Math.round(debate.confidence * 100)}%` : '';
  const description = `${verdict}${confidence ? ` (${confidence} confidence)` : ''} — Multi-agent AI debate on Aragora`;

  return {
    title: `${topic} | ARAGORA`,
    description,
    openGraph: {
      title: topic,
      description,
      type: 'article',
      siteName: 'ARAGORA',
    },
    twitter: {
      card: 'summary_large_image',
      title: topic,
      description,
    },
  };
}
```

**Step 2: Create OG image using next/og**

Create `live/src/app/(standalone)/debate/[[...id]]/opengraph-image.tsx`:

```tsx
import { ImageResponse } from 'next/og';

export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default async function OGImage({ params }: { params: Promise<{ id?: string[] }> }) {
  const { id } = await params;
  const debateId = id?.[0];
  // Fetch debate for topic + verdict
  // Render branded card with topic, verdict, agent count, Aragora logo
}
```

**Step 3: Test OG tags**

Use `curl -s http://localhost:3000/debate/{id} | grep "og:"` to verify metadata.

**Step 4: Commit**

```bash
git add live/src/app/'(standalone)'/debate/
git commit -m "feat: rich OpenGraph metadata and dynamic OG image for shared debates"
```

---

### Task 5: Add "Run your own debate" CTA and topic pre-fill

**Files:**
- Modify: `live/src/app/(standalone)/debate/[[...id]]/DebateViewerWrapper.tsx`
- Modify: `live/src/app/try/page.tsx`

**Step 1: Add CTA to debate viewer**

At the bottom of the saved debate view, add:

```tsx
<a href={`/try?topic=${encodeURIComponent(topic.slice(0, 200))}`}
   className="block w-full text-center py-4 bg-[var(--acid-green)] text-black font-mono font-bold">
  RUN YOUR OWN DEBATE →
</a>
```

**Step 2: Read topic from URL params on /try**

In `live/src/app/try/page.tsx`, read `searchParams.topic` and pre-fill the input:

```tsx
export default function TryPage({ searchParams }: { searchParams: Promise<{ topic?: string }> }) {
  const params = use(searchParams);
  const [question, setQuestion] = useState(params.topic || '');
```

**Step 3: Test the viral loop**

1. Visit `/try` → submit question → get result with share button
2. Copy share link → open in new tab → see full debate
3. Click "RUN YOUR OWN DEBATE" → lands on `/try` with topic pre-filled
4. Submit → get new result → share again

**Step 4: Commit**

```bash
git add live/src/app/try/page.tsx live/src/app/'(standalone)'/debate/
git commit -m "feat: viral loop — Run your own debate CTA with topic pre-fill"
```

---

### Task 6: Final integration test and push

**Step 1: Full loop test**

Run the complete viral loop manually:
- `/try` → submit → result with share → copy link → paste in new tab → debate renders → CTA → `/try?topic=` → pre-filled → submit → new result

**Step 2: Build check**

```bash
cd live && npm run build
```
Verify no TypeScript errors.

**Step 3: Commit any fixes and push**

```bash
git push origin HEAD
```

**Step 4: Create PR**

```bash
gh pr create --title "feat: viral-shareable debate experience" --body "..."
```
