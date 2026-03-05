'use client';

/**
 * Public EU AI Act Compliance Page (standalone, no auth required).
 *
 * Sections:
 *   1. Hero with deadline countdown
 *   2. Interactive risk classifier (demo fallback when backend unavailable)
 *   3. Article preview showing what a compliance bundle contains
 *   4. CTA to run a debate and generate real bundles
 */

import { useState, useCallback, useMemo } from 'react';
import Link from 'next/link';
import { useTheme } from '@/context/ThemeContext';
import { Header } from '@/components/landing/Header';
import { Footer } from '@/components/landing/Footer';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RiskClassification {
  risk_level: 'unacceptable' | 'high' | 'limited' | 'minimal';
  annex_iii_categories: string[];
  applicable_articles: string[];
  matched_keywords: string[];
  confidence: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SAMPLE_USE_CASES = [
  { label: 'Hiring AI', description: 'AI system that screens job applicants, scores resumes, and recommends candidates for interview based on historical hiring data.' },
  { label: 'Medical Diagnosis', description: 'AI-assisted diagnostic system that analyzes medical imaging and patient history to suggest differential diagnoses.' },
  { label: 'Credit Scoring', description: 'Automated creditworthiness scoring system that evaluates loan applications using financial history and behavioral patterns.' },
  { label: 'Content Recs', description: 'AI system that recommends articles and videos based on browsing history for a news platform.' },
];

const RISK_STYLES: Record<string, { bg: string; border: string; text: string; label: string }> = {
  unacceptable: { bg: '#fef2f2', border: '#fca5a5', text: '#dc2626', label: 'PROHIBITED' },
  high: { bg: '#fff7ed', border: '#fdba74', text: '#ea580c', label: 'HIGH RISK' },
  limited: { bg: '#fefce8', border: '#fde047', text: '#ca8a04', label: 'LIMITED RISK' },
  minimal: { bg: '#f0fdf4', border: '#86efac', text: '#16a34a', label: 'MINIMAL RISK' },
};

const RISK_STYLES_DARK: Record<string, { bg: string; border: string; text: string }> = {
  unacceptable: { bg: 'rgba(220,38,38,0.1)', border: 'rgba(220,38,38,0.4)', text: '#ef4444' },
  high: { bg: 'rgba(234,88,12,0.1)', border: 'rgba(234,88,12,0.4)', text: '#f97316' },
  limited: { bg: 'rgba(202,138,4,0.1)', border: 'rgba(202,138,4,0.4)', text: '#eab308' },
  minimal: { bg: 'rgba(22,163,74,0.1)', border: 'rgba(22,163,74,0.4)', text: '#22c55e' },
};

const ARTICLES_PREVIEW = [
  {
    number: '12',
    title: 'Record-Keeping',
    icon: '\uD83D\uDCDD',
    description: 'Complete event logs of every debate phase — propose, critique, revise, vote, synthesize. Technical documentation per Annex IV. Configurable retention policies.',
    fields: ['Event log (47+ event types)', 'Technical documentation (Annex IV)', 'Retention policy (365+ days)'],
  },
  {
    number: '13',
    title: 'Transparency',
    icon: '\uD83D\uDD0D',
    description: 'Provider identity, intended purpose, known risks, and output interpretation guidance. Every agent\'s model identity disclosed in decision receipts.',
    fields: ['Provider identity & contact', 'Known risks & limitations', 'Output interpretation guide'],
  },
  {
    number: '14',
    title: 'Human Oversight',
    icon: '\uD83D\uDC64',
    description: 'Human-on-the-loop approval via receipt gating. Override and stop mechanisms. Automation bias safeguards via contrarian agents and dissent tracking.',
    fields: ['Oversight model definition', 'Bias safeguards (3+ mechanisms)', 'Override & kill switch docs'],
  },
];

// ---------------------------------------------------------------------------
// Demo classification fallback
// ---------------------------------------------------------------------------

function getDemoClassification(description: string): RiskClassification {
  const lower = description.toLowerCase();
  const isHigh = lower.includes('hiring') || lower.includes('credit') || lower.includes('medical') || lower.includes('diagnostic') || lower.includes('loan');
  const isUnacceptable = lower.includes('social scoring') || lower.includes('subliminal') || lower.includes('biometric categorization');

  if (isUnacceptable) {
    return { risk_level: 'unacceptable', annex_iii_categories: ['Article 5 prohibited practices'], applicable_articles: ['Article 5'], matched_keywords: ['social scoring'], confidence: 0.95 };
  }
  if (isHigh) {
    const categories = lower.includes('hiring') ? ['Employment, workers management'] : lower.includes('credit') || lower.includes('loan') ? ['Access to essential private and public services'] : ['Medical devices (Annex II)'];
    const keywords = lower.includes('hiring') ? ['hiring', 'applicant'] : lower.includes('credit') ? ['credit', 'scoring'] : ['diagnostic', 'medical'];
    return { risk_level: 'high', annex_iii_categories: categories, applicable_articles: ['Article 9', 'Article 12', 'Article 13', 'Article 14', 'Article 15'], matched_keywords: keywords, confidence: 0.92 };
  }
  return { risk_level: 'minimal', annex_iii_categories: [], applicable_articles: ['Article 52'], matched_keywords: [], confidence: 0.85 };
}

// ---------------------------------------------------------------------------
// Deadline countdown
// ---------------------------------------------------------------------------

function useDeadlineCountdown(): { days: number; label: string } {
  const deadline = new Date('2026-08-02T00:00:00Z');
  const now = new Date();
  const diff = deadline.getTime() - now.getTime();
  const days = Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)));
  const label = days === 0 ? 'Deadline passed' : `${days} days until enforcement`;
  return { days, label };
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CompliancePage() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const deadline = useDeadlineCountdown();

  const [useCase, setUseCase] = useState('');
  const [classification, setClassification] = useState<RiskClassification | null>(null);
  const [classifying, setClassifying] = useState(false);

  const classify = useCallback(async () => {
    if (!useCase.trim()) return;
    setClassifying(true);
    setClassification(null);

    try {
      const response = await fetch('/api/v2/compliance/eu-ai-act/classify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: useCase }),
      });
      if (response.ok) {
        const data = await response.json();
        setClassification(data.classification || data);
      } else {
        setClassification(getDemoClassification(useCase));
      }
    } catch {
      setClassification(getDemoClassification(useCase));
    } finally {
      setClassifying(false);
    }
  }, [useCase]);

  const riskStyle = useMemo(() => {
    if (!classification) return null;
    const styles = isDark ? RISK_STYLES_DARK : RISK_STYLES;
    return styles[classification.risk_level] || styles.minimal;
  }, [classification, isDark]);

  const riskLabel = classification ? (RISK_STYLES[classification.risk_level]?.label || 'CLASSIFIED') : '';

  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--bg)', color: 'var(--text)' }}>
      <Header />

      {/* ================================================================= */}
      {/* HERO: Headline + deadline countdown */}
      {/* ================================================================= */}
      <section
        className="px-4 text-center"
        style={{
          paddingTop: '96px',
          paddingBottom: '80px',
          fontFamily: 'var(--font-landing)',
        }}
      >
        <div className="max-w-2xl mx-auto">
          {/* Deadline badge */}
          <div
            className="inline-flex items-center gap-2 mb-8"
            style={{
              padding: '6px 16px',
              borderRadius: 'var(--radius-button)',
              backgroundColor: isDark ? 'rgba(234,88,12,0.1)' : '#fff7ed',
              border: `1px solid ${isDark ? 'rgba(234,88,12,0.3)' : '#fdba74'}`,
              fontSize: '13px',
              fontFamily: 'var(--font-landing)',
              color: isDark ? '#f97316' : '#ea580c',
            }}
          >
            <span style={{ fontSize: '16px' }}>{'\u23F0'}</span>
            <span style={{ fontWeight: 600 }}>{deadline.label}</span>
            <span style={{ opacity: 0.7 }}>| August 2, 2026</span>
          </div>

          <h1
            style={{
              fontSize: isDark ? '36px' : '42px',
              fontWeight: 600,
              color: 'var(--text)',
              fontFamily: 'var(--font-landing)',
              lineHeight: 1.2,
              marginBottom: '20px',
            }}
          >
            EU AI Act Compliance{' '}
            <span style={{ color: 'var(--accent)' }}>in Minutes</span>
          </h1>

          <p
            className="max-w-md mx-auto"
            style={{
              fontSize: isDark ? '15px' : '17px',
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-landing)',
              lineHeight: 1.6,
              marginBottom: '16px',
            }}
          >
            Classify your AI system&apos;s risk level, then generate Article 12, 13, and 14 compliance artifacts from any Aragora decision receipt.
          </p>

          <p
            style={{
              fontSize: '13px',
              color: 'var(--text-muted)',
              opacity: 0.6,
              fontFamily: 'var(--font-landing)',
            }}
          >
            Penalties for non-compliance: up to {'\u20AC'}35M or 7% of global annual revenue
          </p>
        </div>
      </section>

      {/* ================================================================= */}
      {/* RISK CLASSIFIER */}
      {/* ================================================================= */}
      <section
        className="px-4"
        style={{
          paddingTop: '80px',
          paddingBottom: '80px',
          borderTop: '1px solid var(--border)',
          fontFamily: 'var(--font-landing)',
        }}
      >
        <div className="max-w-2xl mx-auto">
          <p
            className="text-center uppercase tracking-widest"
            style={{
              fontSize: isDark ? '11px' : '12px',
              color: 'var(--text-muted)',
              marginBottom: '20px',
            }}
          >
            {isDark ? '> RISK CLASSIFIER' : 'RISK CLASSIFIER'}
          </p>

          <h2
            className="text-center"
            style={{
              fontSize: isDark ? '24px' : '28px',
              fontWeight: 600,
              color: 'var(--text)',
              marginBottom: '12px',
            }}
          >
            What does your AI system do?
          </h2>

          <p
            className="text-center max-w-md mx-auto"
            style={{
              fontSize: '15px',
              color: 'var(--text-muted)',
              marginBottom: '40px',
            }}
          >
            Describe your use case and we&apos;ll classify it against Annex III categories.
          </p>

          {/* Sample use case chips */}
          <div className="flex flex-wrap justify-center gap-2 mb-6">
            {SAMPLE_USE_CASES.map((sample) => (
              <button
                key={sample.label}
                onClick={() => { setUseCase(sample.description); setClassification(null); }}
                className="transition-all hover:scale-[1.02]"
                style={{
                  padding: '6px 14px',
                  fontSize: '13px',
                  fontFamily: 'var(--font-landing)',
                  borderRadius: 'var(--radius-button)',
                  border: '1px solid var(--border)',
                  backgroundColor: 'var(--surface)',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                }}
              >
                {sample.label}
              </button>
            ))}
          </div>

          {/* Textarea */}
          <textarea
            value={useCase}
            onChange={(e) => { setUseCase(e.target.value); setClassification(null); }}
            placeholder="Describe your AI system's purpose and functionality..."
            rows={3}
            className="w-full focus:outline-none transition-all resize-none"
            style={{
              backgroundColor: 'var(--surface)',
              border: '2px solid var(--border)',
              color: 'var(--text)',
              fontFamily: 'var(--font-landing)',
              fontSize: '15px',
              lineHeight: 1.6,
              borderRadius: 'var(--radius-input)',
              padding: '16px 18px',
              boxShadow: isDark ? 'none' : 'var(--shadow-card)',
            }}
            onFocus={(e) => { e.currentTarget.style.borderColor = 'var(--accent)'; }}
            onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; }}
          />

          <button
            onClick={classify}
            disabled={!useCase.trim() || classifying}
            className="w-full font-semibold transition-all hover:scale-[1.01] active:scale-[0.99] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            style={{
              backgroundColor: 'var(--accent)',
              color: 'var(--bg)',
              fontFamily: 'var(--font-landing)',
              fontSize: '15px',
              borderRadius: 'var(--radius-button)',
              padding: '14px 24px',
              marginTop: '12px',
              boxShadow: isDark ? '0 0 20px var(--accent-glow)' : '0 2px 8px var(--accent-glow)',
            }}
          >
            {classifying ? 'Classifying...' : isDark ? '> Classify Risk Level' : 'Classify Risk Level'}
          </button>

          {/* Classification result */}
          {classification && riskStyle && (
            <div
              className="mt-8"
              style={{
                padding: '24px',
                borderRadius: 'var(--radius-card)',
                backgroundColor: riskStyle.bg,
                border: `2px solid ${riskStyle.border}`,
              }}
            >
              <div className="flex items-center justify-between mb-4">
                <span style={{ fontSize: '20px', fontWeight: 700, color: riskStyle.text, fontFamily: 'var(--font-landing)' }}>
                  {riskLabel}
                </span>
                <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                  {(classification.confidence * 100).toFixed(0)}% confidence
                </span>
              </div>

              {classification.annex_iii_categories.length > 0 && (
                <div style={{ marginBottom: '12px' }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Annex III Categories</span>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {classification.annex_iii_categories.map((cat, i) => (
                      <span
                        key={i}
                        style={{
                          padding: '4px 10px',
                          fontSize: '13px',
                          borderRadius: 'var(--radius-button)',
                          backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)',
                          color: 'var(--text)',
                          fontFamily: 'var(--font-landing)',
                        }}
                      >
                        {cat}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Applicable Articles</span>
                <div className="flex flex-wrap gap-2 mt-2">
                  {classification.applicable_articles.map((art) => (
                    <span
                      key={art}
                      style={{
                        padding: '4px 10px',
                        fontSize: '13px',
                        borderRadius: 'var(--radius-button)',
                        backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)',
                        color: 'var(--text)',
                        fontFamily: 'var(--font-landing)',
                      }}
                    >
                      {art}
                    </span>
                  ))}
                </div>
              </div>

              {classification.risk_level === 'high' && (
                <div
                  className="mt-6 text-center"
                  style={{
                    padding: '12px',
                    borderRadius: 'var(--radius-card)',
                    backgroundColor: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
                    border: '1px solid var(--border)',
                  }}
                >
                  <p style={{ fontSize: '14px', color: 'var(--text)', marginBottom: '8px', fontWeight: 500 }}>
                    High-risk systems require Articles 12, 13, and 14 compliance artifacts.
                  </p>
                  <Link
                    href="/playground/"
                    style={{
                      fontSize: '14px',
                      color: 'var(--accent)',
                      fontWeight: 600,
                      textDecoration: 'underline',
                      textUnderlineOffset: '3px',
                    }}
                  >
                    Run a debate to generate your compliance bundle {'\u2192'}
                  </Link>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* ================================================================= */}
      {/* ARTICLE PREVIEW */}
      {/* ================================================================= */}
      <section
        className="px-4"
        style={{
          paddingTop: '80px',
          paddingBottom: '80px',
          borderTop: '1px solid var(--border)',
          fontFamily: 'var(--font-landing)',
        }}
      >
        <div className="max-w-3xl mx-auto">
          <p
            className="text-center uppercase tracking-widest"
            style={{
              fontSize: isDark ? '11px' : '12px',
              color: 'var(--text-muted)',
              marginBottom: '20px',
            }}
          >
            {isDark ? '> WHAT YOU GET' : 'WHAT YOU GET'}
          </p>

          <h2
            className="text-center"
            style={{
              fontSize: isDark ? '24px' : '28px',
              fontWeight: 600,
              color: 'var(--text)',
              marginBottom: '12px',
            }}
          >
            Three articles, one bundle
          </h2>

          <p
            className="text-center max-w-md mx-auto"
            style={{
              fontSize: '15px',
              color: 'var(--text-muted)',
              marginBottom: '64px',
            }}
          >
            Every Aragora decision receipt generates a complete EU AI Act compliance bundle covering the three mandatory articles for high-risk systems.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {ARTICLES_PREVIEW.map((article) => (
              <div
                key={article.number}
                className="transition-all hover:translate-y-[-2px]"
                style={{
                  backgroundColor: 'var(--surface)',
                  borderRadius: 'var(--radius-card)',
                  border: '1px solid var(--border)',
                  borderTopColor: 'var(--accent)',
                  borderTopWidth: '3px',
                  boxShadow: 'var(--shadow-card)',
                  padding: '28px 22px',
                }}
              >
                <div className="flex items-center gap-3" style={{ marginBottom: '12px' }}>
                  <span style={{ fontSize: '18px' }}>{article.icon}</span>
                  <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text)' }}>
                    Article {article.number}: {article.title}
                  </h3>
                </div>

                <p style={{ fontSize: '14px', color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: '16px' }}>
                  {article.description}
                </p>

                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                  {article.fields.map((field) => (
                    <li
                      key={field}
                      className="flex items-start gap-2"
                      style={{ padding: '4px 0', fontSize: '13px', color: 'var(--text-muted)' }}
                    >
                      <span style={{ color: 'var(--accent)', flexShrink: 0 }}>{isDark ? '+' : '\u2713'}</span>
                      <span>{field}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ================================================================= */}
      {/* CTA */}
      {/* ================================================================= */}
      <section
        className="px-4 text-center"
        style={{
          paddingTop: '80px',
          paddingBottom: '80px',
          borderTop: '1px solid var(--border)',
          fontFamily: 'var(--font-landing)',
        }}
      >
        <div className="max-w-lg mx-auto">
          <h2
            style={{
              fontSize: isDark ? '24px' : '28px',
              fontWeight: 600,
              color: 'var(--text)',
              marginBottom: '12px',
            }}
          >
            Ready to generate your bundle?
          </h2>
          <p style={{ fontSize: '15px', color: 'var(--text-muted)', marginBottom: '32px', lineHeight: 1.6 }}>
            Run a multi-model debate on any decision. Aragora generates a cryptographically signed compliance bundle from the result.
          </p>
          <Link
            href="/playground/"
            className="inline-block font-semibold transition-all hover:scale-[1.01] active:scale-[0.99]"
            style={{
              backgroundColor: 'var(--accent)',
              color: 'var(--bg)',
              fontFamily: 'var(--font-landing)',
              fontSize: '15px',
              borderRadius: 'var(--radius-button)',
              padding: '16px 40px',
              boxShadow: isDark ? '0 0 20px var(--accent-glow)' : '0 2px 8px var(--accent-glow)',
            }}
          >
            {isDark ? '> Start a free debate' : 'Start a free debate'}
          </Link>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', opacity: 0.5, marginTop: '16px' }}>
            No signup required. CLI and API also available.
          </p>
        </div>
      </section>

      <Footer />
    </div>
  );
}
