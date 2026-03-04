import { Metadata } from 'next';
import { DebateViewerWrapper } from './DebateViewerWrapper';
import { fetchDebate } from './fetchDebate';

// Allow runtime debate IDs in standalone/server mode.
// Static export still uses the base route param below.
export const dynamicParams = true;

export async function generateStaticParams() {
  // Only generate the base route - client handles the rest
  return [{ id: undefined }];
}

// Generate dynamic metadata for OG cards
export async function generateMetadata(
  props: { params: Promise<{ id?: string[] }> },
): Promise<Metadata> {
  const params = await props.params;
  const debateId = params.id?.[0];

  // Default metadata for base route
  if (!debateId) {
    return {
      title: 'ARAGORA Debate Viewer',
      description:
        'Watch AI agents debate and reach consensus in real-time',
    };
  }

  const debate = await fetchDebate(debateId);

  // Fallback when debate cannot be loaded server-side
  if (!debate) {
    const shortId = debateId.slice(0, 12);
    return {
      title: `Debate ${shortId} | ARAGORA`,
      description: `Watch debate ${shortId} and follow agent reasoning in real-time.`,
      openGraph: {
        title: `Debate ${shortId}`,
        description: `ARAGORA live debate stream for ${shortId}.`,
        type: 'website',
        siteName: 'ARAGORA // LIVE',
      },
      twitter: {
        card: 'summary',
        title: `Debate ${shortId}`,
        description: `ARAGORA debate ${shortId}`,
      },
    };
  }

  const confidencePercent = Math.round(debate.confidence * 100);
  const ogDescription = `${debate.verdict} (${confidencePercent}% confidence) — Multi-agent AI debate on Aragora`;
  const ogImageUrl = `/api/og/debate/${debateId}`;

  return {
    title: `${debate.topic} | ARAGORA`,
    description: ogDescription,
    openGraph: {
      title: debate.topic,
      description: ogDescription,
      type: 'website',
      siteName: 'ARAGORA // LIVE',
      images: [{ url: ogImageUrl, width: 1200, height: 630, alt: debate.topic }],
    },
    twitter: {
      card: 'summary_large_image',
      title: debate.topic,
      description: ogDescription,
      images: [ogImageUrl],
    },
  };
}

export default async function DebateViewerPage(
  props: { params: Promise<{ id?: string[] }> },
) {
  const params = await props.params;
  const debateId = params.id?.[0];

  // Fetch saved debate data server-side when an ID is present
  const savedDebate = debateId ? await fetchDebate(debateId) : null;

  return <DebateViewerWrapper savedDebate={savedDebate} />;
}
