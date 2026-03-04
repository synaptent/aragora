import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Aragora — AI Models That Debate Your Decisions',
  description:
    'Ask any question and multiple AI models argue every angle, then deliver a verdict with confidence scores, minority opinions, and a full audit trail.',
  openGraph: {
    title: 'Aragora — AI Models That Debate Your Decisions',
    description:
      'Multiple AI models argue every angle. Confidence scores, minority opinions, full audit trails.',
  },
};

export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return children;
}
