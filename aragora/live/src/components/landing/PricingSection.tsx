'use client';

import Link from 'next/link';
import { useTheme } from '@/context/ThemeContext';

interface Tier {
  name: string;
  price: string;
  period: string;
  highlight?: boolean;
  features: string[];
  cta: string;
  href: string;
}

const TIERS: Tier[] = [
  {
    name: 'Free',
    price: '$0',
    period: '/month',
    features: [
      '10 debates per month',
      '3 AI models per debate',
      'Exportable verdicts',
      'No signup required',
    ],
    cta: 'Try it now',
    href: '/playground',
  },
  {
    name: 'Pro',
    price: '$49',
    period: '/seat/mo',
    highlight: true,
    features: [
      'Unlimited debates',
      '10 AI models per debate',
      'All export formats (PDF, JSON, Markdown)',
      'Slack, Teams, and Email delivery',
      'Learns from past decisions',
      'API and CI/CD integration',
    ],
    cta: 'Start free trial',
    href: '/signup?plan=pro',
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    period: '',
    features: [
      'SSO / RBAC / encryption',
      'SOC 2, HIPAA, EU AI Act',
      'Self-hosted option',
      'Dedicated support + SLA',
    ],
    cta: 'Contact sales',
    href: 'mailto:sales@aragora.ai?subject=Enterprise%20Inquiry',
  },
];

export function PricingSection() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <section
      id="pricing"
      className="px-4"
      style={{
        paddingTop: '120px',
        paddingBottom: '120px',
        borderTop: '1px solid var(--border)',
        fontFamily: 'var(--font-landing)',
      }}
    >
      <div className="max-w-3xl mx-auto">
        {/* Section label */}
        <p
          className="text-center uppercase tracking-widest"
          style={{
            fontSize: isDark ? '16px' : '18px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '20px',
          }}
        >
          {isDark ? '> PRICING' : 'PRICING'}
        </p>

        <h2
          className="text-center"
          style={{
            fontSize: isDark ? '24px' : '28px',
            fontWeight: 600,
            color: 'var(--text)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '16px',
          }}
        >
          Start free. Scale when ready.
        </h2>

        <p
          className="text-center max-w-lg mx-auto"
          style={{
            fontSize: isDark ? '14px' : '15px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '64px',
            lineHeight: '1.6',
          }}
        >
          Bring your own API keys. Aragora never marks up LLM costs.
        </p>

        {/* Tier cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {TIERS.map((tier) => {
            const isHighlighted = tier.highlight === true;
            return (
              <div
                key={tier.name}
                className="flex flex-col"
                style={{
                  backgroundColor: 'var(--surface)',
                  borderRadius: 'var(--radius-card)',
                  border: isHighlighted
                    ? '2px solid var(--accent)'
                    : '1px solid var(--border)',
                  boxShadow: isHighlighted ? 'var(--shadow-card-hover)' : 'var(--shadow-card)',
                  padding: '32px 28px',
                }}
              >
                {/* Tier header */}
                <div style={{ marginBottom: '24px' }}>
                  <h3
                    className="font-semibold"
                    style={{
                      fontSize: '14px',
                      color: isHighlighted ? 'var(--accent)' : 'var(--text)',
                      fontFamily: 'var(--font-landing)',
                      textShadow: isDark && isHighlighted ? '0 0 10px var(--accent)' : 'none',
                      marginBottom: '8px',
                    }}
                  >
                    {isDark ? `[${tier.name.toUpperCase()}]` : tier.name}
                  </h3>
                  <div className="flex items-baseline gap-1">
                    <span
                      className="font-bold"
                      style={{ fontSize: '36px', color: 'var(--text)', fontFamily: 'var(--font-landing)' }}
                    >
                      {tier.price}
                    </span>
                    {tier.period && (
                      <span
                        style={{ fontSize: '14px', color: 'var(--text-muted)', fontFamily: 'var(--font-landing)' }}
                      >
                        {tier.period}
                      </span>
                    )}
                  </div>
                </div>

                {/* Features */}
                <ul className="flex-1" style={{ marginBottom: '32px' }}>
                  {tier.features.map((feature) => (
                    <li
                      key={feature}
                      className="flex items-start gap-3"
                      style={{
                        fontFamily: 'var(--font-landing)',
                        fontSize: isDark ? '13px' : '14px',
                        paddingTop: '8px',
                        paddingBottom: '8px',
                      }}
                    >
                      <span style={{ color: 'var(--accent)', marginTop: '1px', flexShrink: 0 }}>
                        {isDark ? '+' : '\u2713'}
                      </span>
                      <span style={{ color: 'var(--text-muted)', lineHeight: '1.5' }}>{feature}</span>
                    </li>
                  ))}
                </ul>

                {/* CTA */}
                <Link
                  href={tier.href}
                  className="block text-center font-semibold transition-opacity hover:opacity-80"
                  style={{
                    fontFamily: 'var(--font-landing)',
                    fontSize: '14px',
                    borderRadius: 'var(--radius-button)',
                    backgroundColor: isHighlighted ? 'var(--accent)' : 'transparent',
                    color: isHighlighted ? 'var(--bg)' : 'var(--accent)',
                    border: isHighlighted ? 'none' : '1px solid var(--accent)',
                    boxShadow: isDark && isHighlighted ? '0 0 20px var(--accent-glow)' : 'none',
                    padding: '14px 24px',
                  }}
                >
                  {tier.cta}
                </Link>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
