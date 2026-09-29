'use client';

import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { ThemeToggle } from '@/components/ThemeToggle';

// Security certifications and compliance
const CERTIFICATIONS = [
  {
    name: 'SOC 2 Type II',
    status: 'In Progress',
    description:
      'Trust Service Criteria for Security, Availability, Processing Integrity, Confidentiality',
    eta: 'Q2 2026',
  },
  {
    name: 'GDPR Compliant',
    status: 'Active',
    description: 'European data protection regulation compliance',
    eta: null,
  },
  {
    name: 'CCPA Compliant',
    status: 'Active',
    description: 'California Consumer Privacy Act compliance',
    eta: null,
  },
];

// Security features
const SECURITY_FEATURES = [
  {
    icon: '🔐',
    title: 'Encryption at Rest',
    description:
      'AES-256 encryption for all stored data including debate content, user information, and credentials.',
  },
  {
    icon: '🔒',
    title: 'Encryption in Transit',
    description: 'TLS 1.3 for all API communications. No unencrypted data transmission.',
  },
  {
    icon: '🛡️',
    title: 'Multi-Factor Authentication',
    description: 'TOTP-based MFA required for all administrative access. Backup codes provided.',
  },
  {
    icon: '📝',
    title: 'Audit Logging',
    description:
      'Comprehensive audit trail with hash chain integrity verification. 7-year retention.',
  },
  {
    icon: '🚦',
    title: 'Rate Limiting',
    description:
      'Per-endpoint rate limiting with configurable thresholds. Protection against abuse.',
  },
  {
    icon: '🏢',
    title: 'Multi-Tenant Isolation',
    description: 'Complete data isolation between organizations. Row-level security enforced.',
  },
];

// Data handling practices
const DATA_PRACTICES = [
  {
    title: 'Data Minimization',
    description: 'We only collect data necessary for service delivery.',
  },
  {
    title: 'Purpose Limitation',
    description: 'Your data is used only for the purposes you consent to.',
  },
  {
    title: 'Data Portability',
    description: 'Export your data anytime in standard formats (JSON, CSV).',
  },
  { title: 'Right to Deletion', description: 'Request deletion of your data at any time.' },
];

// Security contacts
const SECURITY_CONTACTS = [
  {
    title: 'Security Issues',
    email: 'security@aragora.ai',
    description: 'Report vulnerabilities or security concerns',
  },
  {
    title: 'Privacy Inquiries',
    email: 'privacy@aragora.ai',
    description: 'Data subject requests and privacy questions',
  },
  {
    title: 'DPO (EU/EEA)',
    email: 'dpo@aragora.ai',
    description: 'Data Protection Officer for EU/EEA users',
  },
];

export default function SecurityPage() {
  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link
              href="/"
              className="text-[var(--accent)] font-theme-data font-bold hover:text-[var(--acid-cyan)] transition-colors"
            >
              [ARAGORA]
            </Link>
            <div className="flex items-center gap-4">
              <Link
                href="/about"
                className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                [ABOUT]
              </Link>
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Hero */}
        <section className="py-16 px-4 border-b border-[var(--accent)]/20">
          <div className="container mx-auto max-w-4xl text-center">
            <div className="text-6xl mb-6">🛡️</div>
            <h1 className="text-3xl font-theme-data text-[var(--accent)] mb-4">Security Portal</h1>
            <p className="text-text-muted font-theme-data max-w-2xl mx-auto">
              Aragora is built with security-first principles. We protect your data with
              industry-standard encryption, comprehensive audit logging, and strict access controls.
            </p>
          </div>
        </section>

        {/* Compliance Status */}
        <section className="py-12 px-4 bg-surface/30">
          <div className="container mx-auto max-w-4xl">
            <h2 className="text-2xl font-theme-data text-[var(--accent)] mb-8 text-center">
              Compliance Status
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {CERTIFICATIONS.map((cert) => (
                <div key={cert.name} className="border border-[var(--accent)]/30 p-6 bg-bg/50">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-[var(--acid-cyan)] font-theme-data font-bold">
                      {cert.name}
                    </h3>
                    <span
                      className={`text-xs font-theme-data px-2 py-1 ${
                        cert.status === 'Active'
                          ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                          : 'bg-warning/20 text-warning'
                      }`}
                    >
                      {cert.status}
                    </span>
                  </div>
                  <p className="text-text-muted text-sm font-theme-data mb-2">{cert.description}</p>
                  {cert.eta && (
                    <p className="text-text-muted/60 text-xs font-theme-data">
                      Expected: {cert.eta}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Security Features */}
        <section className="py-12 px-4">
          <div className="container mx-auto max-w-5xl">
            <h2 className="text-2xl font-theme-data text-[var(--accent)] mb-8 text-center">
              Security Features
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {SECURITY_FEATURES.map((feature) => (
                <div
                  key={feature.title}
                  className="border border-[var(--accent)]/20 p-5 bg-surface/20"
                >
                  <div className="flex items-center gap-3 mb-3">
                    <span className="text-2xl">{feature.icon}</span>
                    <h3 className="text-[var(--acid-cyan)] font-theme-data font-bold text-sm">
                      {feature.title}
                    </h3>
                  </div>
                  <p className="text-text-muted text-xs font-theme-data">{feature.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Data Practices */}
        <section className="py-12 px-4 bg-surface/30">
          <div className="container mx-auto max-w-4xl">
            <h2 className="text-2xl font-theme-data text-[var(--accent)] mb-8 text-center">
              Data Practices
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {DATA_PRACTICES.map((practice) => (
                <div key={practice.title} className="flex items-start gap-3">
                  <span className="text-[var(--accent)] mt-1">✓</span>
                  <div>
                    <h3 className="text-[var(--acid-cyan)] font-theme-data font-bold text-sm">
                      {practice.title}
                    </h3>
                    <p className="text-text-muted text-xs font-theme-data">
                      {practice.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-8 text-center">
              <Link
                href="/privacy"
                className="inline-flex items-center gap-2 px-6 py-2 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/10 transition-colors"
              >
                View Privacy Policy →
              </Link>
            </div>
          </div>
        </section>

        {/* Responsible Disclosure */}
        <section className="py-12 px-4">
          <div className="container mx-auto max-w-4xl">
            <h2 className="text-2xl font-theme-data text-[var(--accent)] mb-8 text-center">
              Responsible Disclosure
            </h2>
            <div className="border border-[var(--accent)]/30 p-6 bg-surface/20">
              <p className="text-text-muted font-theme-data text-sm mb-6">
                We value the security research community and appreciate responsible disclosure of
                any vulnerabilities. If you discover a security issue, please report it to us
                privately before any public disclosure.
              </p>

              <h3 className="text-[var(--acid-cyan)] font-theme-data font-bold mb-4">
                Disclosure Guidelines
              </h3>
              <ul className="space-y-2 text-text-muted text-sm font-theme-data mb-6">
                <li className="flex items-start gap-2">
                  <span className="text-[var(--accent)]">1.</span>
                  <span>Email security@aragora.ai with details of the vulnerability</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-[var(--accent)]">2.</span>
                  <span>
                    Include steps to reproduce, potential impact, and any proof-of-concept
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-[var(--accent)]">3.</span>
                  <span>Allow up to 90 days for remediation before public disclosure</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-[var(--accent)]">4.</span>
                  <span>Do not access, modify, or delete data belonging to other users</span>
                </li>
              </ul>

              <h3 className="text-[var(--acid-cyan)] font-theme-data font-bold mb-4">In Scope</h3>
              <ul className="space-y-1 text-text-muted text-sm font-theme-data mb-6">
                <li>• API endpoints (api.aragora.ai)</li>
                <li>• WebSocket connections</li>
                <li>• Authentication and authorization flows</li>
                <li>• Data exposure vulnerabilities</li>
                <li>• Multi-tenant isolation bypass</li>
              </ul>

              <h3 className="text-[var(--acid-cyan)] font-theme-data font-bold mb-4">
                Out of Scope
              </h3>
              <ul className="space-y-1 text-text-muted text-sm font-theme-data">
                <li>• Third-party services (Anthropic, OpenAI, Stripe)</li>
                <li>• Physical security</li>
                <li>• Social engineering attacks</li>
                <li>• Denial of service attacks</li>
                <li>• Spam or rate limiting tests that impact service availability</li>
              </ul>
            </div>
          </div>
        </section>

        {/* Security Contacts */}
        <section className="py-12 px-4 bg-surface/30">
          <div className="container mx-auto max-w-4xl">
            <h2 className="text-2xl font-theme-data text-[var(--accent)] mb-8 text-center">
              Contact Us
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {SECURITY_CONTACTS.map((contact) => (
                <div
                  key={contact.title}
                  className="border border-[var(--accent)]/20 p-5 bg-bg/50 text-center"
                >
                  <h3 className="text-[var(--acid-cyan)] font-theme-data font-bold mb-2">
                    {contact.title}
                  </h3>
                  <a
                    href={`mailto:${contact.email}`}
                    className="text-[var(--accent)] font-theme-data text-sm hover:underline block mb-2"
                  >
                    {contact.email}
                  </a>
                  <p className="text-text-muted text-xs font-theme-data">{contact.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Trust Center Links */}
        <section className="py-12 px-4">
          <div className="container mx-auto max-w-4xl">
            <h2 className="text-2xl font-theme-data text-[var(--accent)] mb-8 text-center">
              Documentation
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                { title: 'Privacy Policy', href: '/privacy', desc: 'How we handle your data' },
                { title: 'Terms of Service', href: '/terms', desc: 'Service agreement' },
                { title: 'Status Page', href: '/system-status', desc: 'Service availability' },
                { title: 'API Docs', href: '/developer', desc: 'Technical documentation' },
              ].map((link) => (
                <Link
                  key={link.title}
                  href={link.href}
                  className="border border-[var(--accent)]/20 p-4 bg-surface/20 hover:bg-surface/40 transition-colors block"
                >
                  <h3 className="text-[var(--acid-cyan)] font-theme-data font-bold text-sm mb-1">
                    {link.title}
                  </h3>
                  <p className="text-text-muted text-xs font-theme-data">{link.desc}</p>
                </Link>
              ))}
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-12 border-t border-[var(--accent)]/20">
          <div className="container mx-auto px-4">
            <div className="text-[var(--accent)]/50 mb-4">{'═'.repeat(50)}</div>
            <div className="flex justify-center gap-6 mb-6">
              <Link
                href="/"
                className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                Home
              </Link>
              <Link
                href="/about"
                className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                About
              </Link>
              <Link
                href="/privacy"
                className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                Privacy
              </Link>
              <Link
                href="/system-status"
                className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                Status
              </Link>
              <a
                href="mailto:security@aragora.ai"
                className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                Contact
              </a>
            </div>
            <p className="text-text-muted mb-2">Security is our priority.</p>
            <p className="text-text-muted/60">Last updated: January 2026</p>
            <div className="text-[var(--accent)]/50 mt-4">{'═'.repeat(50)}</div>
          </div>
        </footer>
      </main>
    </>
  );
}
