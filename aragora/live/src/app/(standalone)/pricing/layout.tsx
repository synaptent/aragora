import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Pricing — Aragora',
  description:
    'Start free with 10 debates per month. Upgrade to Pro for unlimited debates, CI/CD integration, and cross-debate memory. Enterprise plans include SSO, SOC 2, and self-hosted deployment.',
  openGraph: {
    title: 'Pricing — Aragora',
    description:
      'Start free. Scale when ready. Bring your own API keys — Aragora never marks up LLM costs.',
  },
};

export default function PricingLayout({ children }: { children: React.ReactNode }) {
  return children;
}
