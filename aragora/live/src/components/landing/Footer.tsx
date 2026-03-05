'use client';

import Link from 'next/link';
import { useTheme } from '@/context/ThemeContext';

const NAV_LINKS = [
  { href: '/about', label: 'About' },
  { href: '/pricing', label: 'Pricing' },
  { href: '/developer', label: 'Docs' },
  { href: 'mailto:support@aragora.ai', label: 'Support' },
];

export function Footer() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <footer
      className="px-4"
      style={{
        paddingTop: '80px',
        paddingBottom: '60px',
        borderTop: '1px solid var(--border)',
        fontFamily: 'var(--font-landing)',
      }}
    >
      <div className="max-w-2xl mx-auto text-center">
        {/* Call to action statement */}
        <p
          style={{
            fontSize: '14px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '32px',
          }}
        >
          No signup required. No API keys required. First verdict within 5 minutes.
        </p>

        {/* CTA buttons */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4" style={{ marginBottom: '48px' }}>
          <button
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            className="text-sm font-semibold transition-opacity hover:opacity-80 cursor-pointer"
            style={{
              backgroundColor: 'var(--accent)',
              color: 'var(--bg)',
              fontFamily: 'var(--font-landing)',
              borderRadius: 'var(--radius-button)',
              boxShadow: isDark ? '0 0 20px var(--accent-glow)' : 'none',
              border: 'none',
              padding: '18px 48px',
            }}
          >
            Try it now
          </button>
          <Link
            href="/signup"
            className="text-sm font-semibold transition-colors hover:opacity-80"
            style={{
              fontFamily: 'var(--font-landing)',
              borderRadius: 'var(--radius-button)',
              border: '1px solid var(--border)',
              color: 'var(--text-muted)',
              backgroundColor: 'transparent',
              padding: '18px 48px',
            }}
          >
            Create an account
          </Link>
        </div>

        {/* Nav links */}
        <div className="flex items-center justify-center gap-6 mb-8">
          {NAV_LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="text-xs transition-colors hover:opacity-80"
              style={{
                color: 'var(--text-muted)',
                opacity: 0.5,
                fontFamily: 'var(--font-landing)',
              }}
            >
              {link.label}
            </a>
          ))}
        </div>

        {/* Tagline */}
        <p
          className="text-xs"
          style={{
            color: 'var(--text-muted)',
            opacity: 0.4,
            fontFamily: 'var(--font-landing)',
          }}
        >
          {isDark ? '> AI decisions you can trust.' : 'AI decisions you can trust.'}
        </p>
      </div>
    </footer>
  );
}
