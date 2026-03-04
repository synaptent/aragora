'use client';

import Link from 'next/link';
import { useTheme } from '@/context/ThemeContext';
import { Header } from '@/components/landing/Header';
import { Footer } from '@/components/landing/Footer';
import { Logo } from '@/components/Logo';
import { WhyAragoraSection } from '@/components/landing/WhyAragoraSection';
import { CapabilitiesSection } from '@/components/landing/CapabilitiesSection';
import { USE_CASES, CAPABILITIES } from '../../(app)/about/constants';

export default function AboutPage() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--bg)', color: 'var(--text)' }}>
      <Header />

      {/* Hero */}
      <section
        className="px-4"
        style={{
          paddingTop: '100px',
          paddingBottom: '80px',
          fontFamily: 'var(--font-landing)',
        }}
      >
        <div className="max-w-3xl mx-auto text-center">
          <div className="flex justify-center mb-6">
            <Logo size="lg" pixelSize={48} />
          </div>

          <h1
            style={{
              fontSize: isDark ? '32px' : '36px',
              fontWeight: 700,
              color: 'var(--text)',
              fontFamily: 'var(--font-landing)',
              marginBottom: '16px',
            }}
          >
            {isDark ? '> ARAGORA' : 'Aragora'}
          </h1>

          <p
            style={{
              fontSize: isDark ? '18px' : '20px',
              color: 'var(--accent)',
              fontFamily: 'var(--font-landing)',
              marginBottom: '16px',
            }}
          >
            The Decision Integrity Platform
          </p>

          <p
            className="max-w-xl mx-auto"
            style={{
              fontSize: isDark ? '14px' : '16px',
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-landing)',
              lineHeight: '1.7',
              marginBottom: '24px',
            }}
          >
            Multiple AI models debate your decisions. Ask any question and get a verdict
            with confidence scores, minority opinions, and a full audit trail.
          </p>

          {/* Etymology */}
          <p
            style={{
              fontSize: '13px',
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-landing)',
              opacity: 0.7,
              marginBottom: '40px',
            }}
          >
            <span style={{ color: 'var(--accent)' }}>ar-</span> (Latin: toward, enhanced)
            {' + '}
            <span style={{ color: 'var(--accent)' }}>agora</span> (Greek: marketplace of ideas)
          </p>

          {/* CTA */}
          <div className="flex justify-center gap-4 flex-wrap">
            <Link
              href="/landing"
              className="font-semibold transition-opacity hover:opacity-80"
              style={{
                fontSize: '14px',
                fontFamily: 'var(--font-landing)',
                borderRadius: 'var(--radius-button)',
                backgroundColor: 'var(--accent)',
                color: 'var(--bg)',
                boxShadow: isDark ? '0 0 20px var(--accent-glow)' : 'none',
                padding: '14px 32px',
              }}
            >
              Try it now
            </Link>
            <Link
              href="/signup"
              className="font-semibold transition-opacity hover:opacity-80"
              style={{
                fontSize: '14px',
                fontFamily: 'var(--font-landing)',
                borderRadius: 'var(--radius-button)',
                border: '1px solid var(--border)',
                color: 'var(--text-muted)',
                backgroundColor: 'transparent',
                padding: '14px 32px',
              }}
            >
              Create an account
            </Link>
          </div>
        </div>
      </section>

      {/* Platform Capabilities */}
      <section
        className="px-4"
        style={{
          paddingTop: '60px',
          paddingBottom: '60px',
          borderTop: '1px solid var(--border)',
          fontFamily: 'var(--font-landing)',
        }}
      >
        <div className="max-w-3xl mx-auto">
          <p
            className="text-center uppercase tracking-widest"
            style={{
              fontSize: isDark ? '16px' : '18px',
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-landing)',
              marginBottom: '20px',
            }}
          >
            {isDark ? '> PLATFORM' : 'PLATFORM'}
          </p>
          <h2
            className="text-center"
            style={{
              fontSize: isDark ? '24px' : '28px',
              fontWeight: 600,
              color: 'var(--text)',
              fontFamily: 'var(--font-landing)',
              marginBottom: '48px',
            }}
          >
            Built for serious decisions
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            {CAPABILITIES.slice(0, 10).map((cap) => (
              <div
                key={cap.label}
                className="text-center"
                style={{
                  backgroundColor: 'var(--surface)',
                  borderRadius: 'var(--radius-card)',
                  border: '1px solid var(--border)',
                  padding: '20px 12px',
                }}
              >
                <div
                  className="font-bold"
                  style={{ fontSize: '24px', color: 'var(--accent)', fontFamily: 'var(--font-landing)' }}
                >
                  {cap.value}
                </div>
                <div
                  style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-landing)', marginTop: '4px' }}
                >
                  {cap.label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <WhyAragoraSection />
      <CapabilitiesSection />

      {/* Use Cases */}
      <section
        className="px-4"
        style={{
          paddingTop: '80px',
          paddingBottom: '80px',
          borderTop: '1px solid var(--border)',
          fontFamily: 'var(--font-landing)',
        }}
      >
        <div className="max-w-4xl mx-auto">
          <p
            className="text-center uppercase tracking-widest"
            style={{
              fontSize: isDark ? '16px' : '18px',
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-landing)',
              marginBottom: '20px',
            }}
          >
            {isDark ? '> USE CASES' : 'USE CASES'}
          </p>
          <h2
            className="text-center"
            style={{
              fontSize: isDark ? '24px' : '28px',
              fontWeight: 600,
              color: 'var(--text)',
              fontFamily: 'var(--font-landing)',
              marginBottom: '48px',
            }}
          >
            What teams use Aragora for
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {USE_CASES.slice(0, 9).map((uc) => (
              <div
                key={uc.title}
                style={{
                  backgroundColor: 'var(--surface)',
                  borderRadius: 'var(--radius-card)',
                  border: '1px solid var(--border)',
                  padding: '24px',
                }}
              >
                <div className="flex items-center gap-3 mb-3">
                  <span style={{ fontSize: '24px' }}>{uc.icon}</span>
                  <div>
                    <h3
                      className="font-semibold"
                      style={{ fontSize: '14px', color: 'var(--text)', fontFamily: 'var(--font-landing)' }}
                    >
                      {uc.title}
                    </h3>
                    <p style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-landing)' }}>
                      {uc.subtitle}
                    </p>
                  </div>
                </div>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                  {uc.examples.map((ex, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2"
                      style={{
                        fontSize: isDark ? '12px' : '13px',
                        color: 'var(--text-muted)',
                        fontFamily: 'var(--font-landing)',
                        paddingTop: '4px',
                        paddingBottom: '4px',
                      }}
                    >
                      <span style={{ color: 'var(--accent)', marginTop: '1px', flexShrink: 0 }}>
                        {isDark ? '+' : '\u2713'}
                      </span>
                      <span>{ex}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
