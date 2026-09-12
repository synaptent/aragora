'use client';

import { useTheme } from '@/context/ThemeContext';

interface Integration {
  name: string;
  icon: React.ReactNode;
}

const INTEGRATIONS: Integration[] = [
  {
    name: 'Slack',
    icon: (
      <svg
        width="28"
        height="28"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect width="3" height="8" x="13" y="2" rx="1.5" />
        <path d="M19 8.5V10h1.5A1.5 1.5 0 1 0 19 8.5" />
        <rect width="3" height="8" x="8" y="14" rx="1.5" />
        <path d="M5 15.5V14H3.5A1.5 1.5 0 1 0 5 15.5" />
        <rect width="8" height="3" x="14" y="13" rx="1.5" />
        <path d="M15.5 19H14v1.5a1.5 1.5 0 1 0 1.5-1.5" />
        <rect width="8" height="3" x="2" y="8" rx="1.5" />
        <path d="M8.5 5H10V3.5A1.5 1.5 0 1 0 8.5 5" />
      </svg>
    ),
  },
  {
    name: 'GitHub',
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0 0 22 12.017C22 6.484 17.522 2 12 2Z" />
      </svg>
    ),
  },
  {
    name: 'Discord',
    icon: (
      <svg
        width="28"
        height="28"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M9 12h.01" />
        <path d="M15 12h.01" />
        <path d="M7.5 7.5c3.5-1 5.5-1 9 0" />
        <path d="M7 16.5c3.5 1 6.5 1 10 0" />
        <path d="M15.5 17c0 1 1.5 3 2 3 1.5 0 2.833-1.667 3.5-3 .667-1.667.5-5.833-1.5-11.5-1.457-1.015-3-1.34-4.5-1.5l-1 2.5" />
        <path d="M8.5 17c0 1-1.356 3-1.832 3-1.429 0-2.698-1.667-3.333-3-.635-1.667-.476-5.833 1.428-11.5C6.151 4.485 7.545 4.16 9 4l1 2.5" />
      </svg>
    ),
  },
  {
    name: 'Teams',
    icon: (
      <svg
        width="28"
        height="28"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect width="7" height="7" x="3" y="3" rx="1" />
        <rect width="7" height="7" x="14" y="3" rx="1" />
        <rect width="7" height="7" x="14" y="14" rx="1" />
        <rect width="7" height="7" x="3" y="14" rx="1" />
      </svg>
    ),
  },
  {
    name: 'Email',
    icon: (
      <svg
        width="28"
        height="28"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect width="20" height="16" x="2" y="4" rx="2" />
        <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
      </svg>
    ),
  },
  {
    name: 'Zapier',
    icon: (
      <svg
        width="28"
        height="28"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />
      </svg>
    ),
  },
  {
    name: 'Webhooks',
    icon: (
      <svg
        width="28"
        height="28"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="m5 12 7-7 7 7" />
        <path d="M12 19V5" />
      </svg>
    ),
  },
];

export function IntegrationsGrid() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <section
      className="px-4"
      style={{
        paddingTop: '120px',
        paddingBottom: '120px',
        borderTop: '1px solid var(--border)',
        fontFamily: 'var(--font-landing)',
      }}
    >
      <div className="max-w-3xl mx-auto text-center">
        <p
          className="text-center uppercase tracking-widest"
          style={{
            fontSize: isDark ? '16px' : '18px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '20px',
          }}
        >
          {isDark ? '> INTEGRATIONS' : 'INTEGRATIONS'}
        </p>
        <p
          style={{
            fontSize: isDark ? '16px' : '18px',
            color: 'var(--text)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '48px',
          }}
        >
          Fits where your team already works.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-8">
          {INTEGRATIONS.map((integration) => (
            <div
              key={integration.name}
              className="flex flex-col items-center gap-2 transition-all opacity-40 hover:opacity-100"
              style={{ color: 'var(--text-muted)' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = 'var(--accent)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'var(--text-muted)';
              }}
            >
              {integration.icon}
              <span className="text-xs" style={{ fontFamily: 'var(--font-landing)' }}>
                {integration.name}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
