'use client';

import { useState, useEffect } from 'react';
import { notFound } from 'next/navigation';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';

// Vertical configurations for landing pages
const VERTICALS = {
  legal: {
    name: 'Legal',
    tagline: 'AI-Powered Legal Analysis & Compliance',
    icon: '\u2696\ufe0f',
    color: 'blue',
    description:
      'Multi-agent debate for contract review, due diligence, regulatory compliance, and legal risk assessment.',
    heroImage: '/images/verticals/legal-hero.png',
    stats: [
      { value: '85%', label: 'Faster contract review' },
      { value: '99.2%', label: 'Clause detection accuracy' },
      { value: '40+', label: 'Jurisdiction support' },
    ],
    useCases: [
      {
        title: 'Contract Review',
        description:
          'Automated analysis of contracts for risks, obligations, and non-standard terms.',
        icon: '\ud83d\udcdd',
        details: [
          'Risk clause detection',
          'Obligation extraction',
          'Term comparison',
          'Redline suggestions',
        ],
      },
      {
        title: 'Due Diligence',
        description: 'Comprehensive document review for M&A, investments, and partnerships.',
        icon: '\ud83d\udd0d',
        details: [
          'Document categorization',
          'Issue flagging',
          'Risk scoring',
          'Summary generation',
        ],
      },
      {
        title: 'Regulatory Compliance',
        description: 'Multi-framework compliance checking against GDPR, CCPA, SOX, and more.',
        icon: '\u2705',
        details: [
          'Policy gap analysis',
          'Compliance mapping',
          'Audit preparation',
          'Remediation tracking',
        ],
      },
      {
        title: 'Legal Research',
        description: 'Case law analysis and precedent research with multi-agent validation.',
        icon: '\ud83d\udcda',
        details: [
          'Case similarity matching',
          'Argument synthesis',
          'Citation verification',
          'Strategy recommendations',
        ],
      },
    ],
    agents: [
      {
        name: 'Contract Analyst',
        specialty: 'Commercial agreements & terms',
        icon: '\ud83d\udcdc',
      },
      {
        name: 'Compliance Officer',
        specialty: 'Regulatory frameworks & policies',
        icon: '\ud83d\udee1\ufe0f',
      },
      { name: 'Risk Assessor', specialty: 'Legal liability & exposure', icon: '\u26a0\ufe0f' },
      { name: 'IP Specialist', specialty: 'Intellectual property & patents', icon: '\ud83d\udca1' },
    ],
    compliance: ['GDPR', 'CCPA', 'SOX', 'HIPAA', 'SEC', 'FTC'],
    testimonial: {
      quote:
        'Aragora reduced our contract review time by 70% while catching edge cases we would have missed.',
      author: 'Sarah Chen',
      role: 'General Counsel',
      company: 'TechCorp Inc.',
    },
  },
  healthcare: {
    name: 'Healthcare',
    tagline: 'Clinical AI with Compliance Built In',
    icon: '\ud83c\udfe5',
    color: 'green',
    description:
      'HIPAA-compliant multi-agent analysis for clinical documentation, research validation, and healthcare operations.',
    heroImage: '/images/verticals/healthcare-hero.png',
    stats: [
      { value: 'HIPAA', label: 'Controls built in' },
      { value: '95%', label: 'Documentation accuracy' },
      { value: '50%', label: 'Time saved on reviews' },
    ],
    useCases: [
      {
        title: 'Clinical Documentation',
        description: 'Review and improve clinical notes, discharge summaries, and medical records.',
        icon: '\ud83d\udccb',
        details: [
          'Note completeness check',
          'Terminology standardization',
          'Coding suggestions',
          'Quality metrics',
        ],
      },
      {
        title: 'Research Validation',
        description: 'Multi-agent review of clinical trial protocols and research methodologies.',
        icon: '\ud83e\uddea',
        details: ['Protocol analysis', 'Statistical review', 'Bias detection', 'Ethics compliance'],
      },
      {
        title: 'Compliance Audits',
        description: 'Automated HIPAA, HITECH, and regulatory compliance checking.',
        icon: '\ud83d\udd10',
        details: ['PHI detection', 'Access logging review', 'Policy compliance', 'Risk assessment'],
      },
      {
        title: 'Care Coordination',
        description: 'AI-assisted care plan review and interdisciplinary communication.',
        icon: '\ud83e\ude7a',
        details: [
          'Care gap analysis',
          'Treatment alignment',
          'Handoff verification',
          'Outcome tracking',
        ],
      },
    ],
    agents: [
      {
        name: 'Clinical Reviewer',
        specialty: 'Medical documentation & coding',
        icon: '\ud83e\udda0',
      },
      {
        name: 'Compliance Auditor',
        specialty: 'HIPAA & regulatory adherence',
        icon: '\ud83d\udee1\ufe0f',
      },
      { name: 'Research Validator', specialty: 'Clinical trial methodology', icon: '\ud83d\udd2c' },
      { name: 'Quality Analyst', specialty: 'Care quality metrics', icon: '\ud83d\udcca' },
    ],
    compliance: ['HIPAA', 'HITECH', 'FDA', '21 CFR Part 11', 'GDPR-Health'],
    testimonial: {
      quote:
        'The multi-agent approach catches inconsistencies in clinical documentation that single-pass AI misses.',
      author: 'Dr. Michael Torres',
      role: 'Chief Medical Officer',
      company: 'Regional Health System',
    },
  },
  finance: {
    name: 'Finance',
    tagline: 'Quantitative Analysis Meets AI Consensus',
    icon: '\ud83d\udcb0',
    color: 'yellow',
    description:
      'Multi-agent financial analysis for investment decisions, risk assessment, and regulatory compliance.',
    heroImage: '/images/verticals/finance-hero.png',
    stats: [
      { value: '360\u00b0', label: 'Analysis coverage' },
      { value: 'Real-time', label: 'Market data integration' },
      { value: 'SOC 2', label: 'Controls implemented' },
    ],
    useCases: [
      {
        title: 'Investment Analysis',
        description:
          'Multi-perspective evaluation of investment opportunities and portfolio decisions.',
        icon: '\ud83d\udcc8',
        details: [
          'Fundamental analysis',
          'Technical indicators',
          'Risk modeling',
          'Scenario planning',
        ],
      },
      {
        title: 'Risk Assessment',
        description: 'Comprehensive risk evaluation with adversarial stress testing.',
        icon: '\u26a1',
        details: ['Market risk', 'Credit risk', 'Operational risk', 'Regulatory risk'],
      },
      {
        title: 'Compliance Review',
        description: 'SEC, FINRA, and global regulatory compliance checking.',
        icon: '\ud83d\udcdd',
        details: ['Trade surveillance', 'Disclosure review', 'AML screening', 'KYC verification'],
      },
      {
        title: 'Due Diligence',
        description: 'M&A and investment due diligence with multi-agent validation.',
        icon: '\ud83d\udd0d',
        details: [
          'Financial modeling',
          'Synergy analysis',
          'Risk identification',
          'Valuation review',
        ],
      },
    ],
    agents: [
      { name: 'Quant Analyst', specialty: 'Quantitative modeling & data', icon: '\ud83d\udcca' },
      {
        name: 'Risk Manager',
        specialty: 'Risk identification & mitigation',
        icon: '\ud83d\udee1\ufe0f',
      },
      { name: 'Compliance Officer', specialty: 'Regulatory requirements', icon: '\u2696\ufe0f' },
      { name: 'Market Strategist', specialty: 'Market dynamics & trends', icon: '\ud83c\udf10' },
    ],
    compliance: ['SEC', 'FINRA', 'SOX', 'GDPR', 'MiFID II', 'Basel III'],
    testimonial: {
      quote:
        "Aragora's adversarial analysis uncovered risks in our portfolio that traditional models missed.",
      author: 'James Wright',
      role: 'Chief Risk Officer',
      company: 'Capital Partners LLC',
    },
  },
  software: {
    name: 'Software Engineering',
    tagline: 'AI Code Review That Thinks Like Your Team',
    icon: '\ud83d\udcbb',
    color: 'purple',
    description:
      'Multi-agent code review, architecture validation, and security analysis for development teams.',
    heroImage: '/images/verticals/software-hero.png',
    stats: [
      { value: '3x', label: 'Faster code reviews' },
      { value: '92%', label: 'Bug detection rate' },
      { value: '25+', label: 'Languages supported' },
    ],
    useCases: [
      {
        title: 'Code Review',
        description: 'Multi-perspective code analysis for quality, security, and best practices.',
        icon: '\ud83d\udd0d',
        details: [
          'Style consistency',
          'Bug detection',
          'Performance issues',
          'Security vulnerabilities',
        ],
      },
      {
        title: 'Architecture Review',
        description: 'System design validation with trade-off analysis.',
        icon: '\ud83c\udfd7\ufe0f',
        details: [
          'Scalability analysis',
          'Pattern compliance',
          'Coupling assessment',
          'Migration planning',
        ],
      },
      {
        title: 'Security Audit',
        description: 'Adversarial security review with red-team perspectives.',
        icon: '\ud83d\udd10',
        details: ['OWASP Top 10', 'Dependency scanning', 'Auth/authz review', 'Data protection'],
      },
      {
        title: 'Tech Debt Assessment',
        description: 'Quantify and prioritize technical debt with multi-agent consensus.',
        icon: '\ud83d\udcb3',
        details: [
          'Debt identification',
          'Impact scoring',
          'Remediation planning',
          'Progress tracking',
        ],
      },
    ],
    agents: [
      {
        name: 'Senior Engineer',
        specialty: 'Code quality & patterns',
        icon: '\ud83d\udc68\u200d\ud83d\udcbb',
      },
      { name: 'Security Researcher', specialty: 'Vulnerability analysis', icon: '\ud83d\udd12' },
      { name: 'Architect', specialty: 'System design & scalability', icon: '\ud83c\udfd7\ufe0f' },
      { name: 'Performance Engineer', specialty: 'Optimization & efficiency', icon: '\u26a1' },
    ],
    compliance: ['SOC 2', 'ISO 27001', 'OWASP', 'PCI DSS', 'GDPR'],
    testimonial: {
      quote:
        'The multi-agent approach catches architectural issues that single-tool analysis completely misses.',
      author: 'Lisa Park',
      role: 'VP of Engineering',
      company: 'ScaleTech Solutions',
    },
  },
  research: {
    name: 'Academic Research',
    tagline: 'Rigorous Peer Review at AI Speed',
    icon: '\ud83c\udf93',
    color: 'cyan',
    description:
      'Multi-agent academic validation for research papers, grant proposals, and literature reviews.',
    heroImage: '/images/verticals/research-hero.png',
    stats: [
      { value: '10x', label: 'Faster literature review' },
      { value: '94%', label: 'Citation accuracy' },
      { value: '50+', label: 'Research domains' },
    ],
    useCases: [
      {
        title: 'Paper Review',
        description: 'Multi-perspective manuscript review mimicking peer review process.',
        icon: '\ud83d\udcc4',
        details: [
          'Methodology critique',
          'Statistical validation',
          'Literature gaps',
          'Writing quality',
        ],
      },
      {
        title: 'Literature Synthesis',
        description: 'Comprehensive literature review with multi-agent validation.',
        icon: '\ud83d\udcda',
        details: ['Source discovery', 'Theme extraction', 'Gap identification', 'Citation mapping'],
      },
      {
        title: 'Grant Proposal Review',
        description: 'Strengthen proposals with adversarial critique and improvement suggestions.',
        icon: '\ud83d\udcdd',
        details: [
          'Significance evaluation',
          'Methodology review',
          'Budget justification',
          'Impact assessment',
        ],
      },
      {
        title: 'Research Validation',
        description: 'Verify research claims and reproducibility with multi-agent analysis.',
        icon: '\u2705',
        details: ['Claim verification', 'Data consistency', 'Method replication', 'Bias detection'],
      },
    ],
    agents: [
      {
        name: 'Domain Expert',
        specialty: 'Subject matter expertise',
        icon: '\ud83e\uddd1\u200d\ud83c\udfeb',
      },
      { name: 'Methodologist', specialty: 'Research design & statistics', icon: '\ud83d\udcca' },
      { name: 'Editor', specialty: 'Academic writing & clarity', icon: '\u270d\ufe0f' },
      { name: 'Skeptic', specialty: 'Critical analysis & challenges', icon: '\ud83e\udd14' },
    ],
    compliance: ['IRB', 'ORCID', 'DOI', 'Open Access Policies'],
    testimonial: {
      quote:
        'Aragora helped us identify methodological issues in our paper before submission, saving months of revision.',
      author: 'Dr. Emily Chen',
      role: 'Associate Professor',
      company: 'Stanford University',
    },
  },
} as const;

type VerticalSlug = keyof typeof VERTICALS;

function getColorClasses(color: string) {
  const colors: Record<string, { primary: string; secondary: string; bg: string; border: string }> =
    {
      blue: {
        primary: 'text-blue-400',
        secondary: 'text-blue-300',
        bg: 'bg-blue-500/10',
        border: 'border-blue-500/30',
      },
      green: {
        primary: 'text-green-400',
        secondary: 'text-green-300',
        bg: 'bg-green-500/10',
        border: 'border-green-500/30',
      },
      yellow: {
        primary: 'text-yellow-400',
        secondary: 'text-yellow-300',
        bg: 'bg-yellow-500/10',
        border: 'border-yellow-500/30',
      },
      purple: {
        primary: 'text-purple-400',
        secondary: 'text-purple-300',
        bg: 'bg-purple-500/10',
        border: 'border-purple-500/30',
      },
      cyan: {
        primary: 'text-cyan-400',
        secondary: 'text-cyan-300',
        bg: 'bg-cyan-500/10',
        border: 'border-cyan-500/30',
      },
    };
  return colors[color] || colors.blue;
}

interface VerticalContentProps {
  slug: string;
}

export default function VerticalContent({ slug }: VerticalContentProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!slug || !(slug in VERTICALS)) {
    notFound();
  }

  const vertical = VERTICALS[slug as VerticalSlug];
  const colors = getColorClasses(vertical.color);

  if (!mounted) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center">
        <div className="text-[var(--accent)] font-theme-data animate-pulse">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg text-text relative overflow-hidden">
      <Scanlines opacity={0.02} />
      <CRTVignette />

      {/* Header */}
      <header className="border-b border-border sticky top-0 z-50 bg-bg/80 backdrop-blur-sm">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link href="/" className="hover:opacity-80 transition-opacity">
            <AsciiBannerCompact />
          </Link>
          <div className="flex items-center gap-4">
            <Link
              href="/verticals"
              className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
            >
              [ALL VERTICALS]
            </Link>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="relative z-10">
        {/* Hero Section */}
        <section className="py-16 px-4 border-b border-border">
          <div className="max-w-6xl mx-auto">
            <div className="flex items-center gap-4 mb-6">
              <span className="text-5xl">{vertical.icon}</span>
              <div>
                <h1 className={`text-4xl font-theme-data font-bold ${colors.primary}`}>
                  {vertical.name}
                </h1>
                <p className="text-xl text-text-muted mt-1">{vertical.tagline}</p>
              </div>
            </div>

            <p className="text-lg text-text max-w-3xl mb-8">{vertical.description}</p>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-6 max-w-2xl">
              {vertical.stats.map((stat, i) => (
                <div key={i} className="text-center">
                  <div className={`text-3xl font-theme-data font-bold ${colors.primary}`}>
                    {stat.value}
                  </div>
                  <div className="text-sm text-text-muted">{stat.label}</div>
                </div>
              ))}
            </div>

            {/* CTA */}
            <div className="mt-10 flex gap-4">
              <Link
                href={`/arena?vertical=${slug}`}
                className={`px-6 py-3 ${colors.bg} border ${colors.border} ${colors.primary} font-theme-data font-bold rounded hover:opacity-80 transition-opacity`}
              >
                Start {vertical.name} Debate
              </Link>
              <Link
                href="/workflows"
                className="px-6 py-3 bg-surface border border-border text-text font-theme-data rounded hover:border-text-muted transition-colors"
              >
                View Templates
              </Link>
            </div>
          </div>
        </section>

        {/* Use Cases */}
        <section className="py-16 px-4 border-b border-border">
          <div className="max-w-6xl mx-auto">
            <h2 className="text-2xl font-theme-data font-bold text-text mb-8">Use Cases</h2>
            <div className="grid md:grid-cols-2 gap-6">
              {vertical.useCases.map((useCase, i) => (
                <div key={i} className={`p-6 bg-surface border ${colors.border} rounded-lg`}>
                  <div className="flex items-start gap-4">
                    <span className="text-3xl">{useCase.icon}</span>
                    <div className="flex-1">
                      <h3 className={`text-lg font-theme-data font-bold ${colors.primary}`}>
                        {useCase.title}
                      </h3>
                      <p className="text-text-muted text-sm mt-1 mb-4">{useCase.description}</p>
                      <div className="flex flex-wrap gap-2">
                        {useCase.details.map((detail, j) => (
                          <span
                            key={j}
                            className={`px-2 py-1 text-xs font-theme-data ${colors.bg} ${colors.primary} rounded`}
                          >
                            {detail}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Specialist Agents */}
        <section className="py-16 px-4 border-b border-border bg-surface/30">
          <div className="max-w-6xl mx-auto">
            <h2 className="text-2xl font-theme-data font-bold text-text mb-8">Specialist Agents</h2>
            <div className="grid md:grid-cols-4 gap-4">
              {vertical.agents.map((agent, i) => (
                <div key={i} className="p-4 bg-bg border border-border rounded-lg text-center">
                  <span className="text-4xl block mb-3">{agent.icon}</span>
                  <h3 className="font-theme-data font-bold text-text">{agent.name}</h3>
                  <p className="text-xs text-text-muted mt-1">{agent.specialty}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Compliance */}
        <section className="py-16 px-4 border-b border-border">
          <div className="max-w-6xl mx-auto">
            <h2 className="text-2xl font-theme-data font-bold text-text mb-8">
              Compliance Frameworks
            </h2>
            <div className="flex flex-wrap gap-3">
              {vertical.compliance.map((framework, i) => (
                <span
                  key={i}
                  className={`px-4 py-2 ${colors.bg} border ${colors.border} ${colors.primary} font-theme-data rounded-lg`}
                >
                  {framework}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* Testimonial */}
        <section className="py-16 px-4 border-b border-border bg-surface/30">
          <div className="max-w-4xl mx-auto text-center">
            <blockquote className="text-xl text-text italic mb-6">
              &ldquo;{vertical.testimonial.quote}&rdquo;
            </blockquote>
            <div className="flex items-center justify-center gap-4">
              <div
                className={`w-12 h-12 rounded-full ${colors.bg} flex items-center justify-center`}
              >
                <span className="text-xl">{vertical.icon}</span>
              </div>
              <div className="text-left">
                <div className={`font-theme-data font-bold ${colors.primary}`}>
                  {vertical.testimonial.author}
                </div>
                <div className="text-sm text-text-muted">
                  {vertical.testimonial.role}, {vertical.testimonial.company}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* CTA Section */}
        <section className="py-20 px-4">
          <div className="max-w-4xl mx-auto text-center">
            <h2 className={`text-3xl font-theme-data font-bold ${colors.primary} mb-4`}>
              Ready to Transform Your {vertical.name} Workflow?
            </h2>
            <p className="text-text-muted mb-8 max-w-2xl mx-auto">
              Start a multi-agent debate with specialized {vertical.name.toLowerCase()} AI agents.
              Get consensus-driven insights in minutes.
            </p>
            <div className="flex justify-center gap-4">
              <Link
                href={`/arena?vertical=${slug}`}
                className="px-8 py-4 bg-[var(--accent)] text-bg font-theme-data font-bold rounded hover:bg-[var(--accent)]/80 transition-colors"
              >
                Start Free Debate
              </Link>
              <Link
                href="/pricing"
                className="px-8 py-4 bg-surface border border-border text-text font-theme-data rounded hover:border-[var(--accent)]/50 transition-colors"
              >
                View Pricing
              </Link>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-border py-8 px-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between text-sm font-theme-data text-text-muted">
          <Link href="/" className="hover:text-[var(--accent)] transition-colors">
            ARAGORA
          </Link>
          <div className="flex gap-6">
            <Link href="/verticals" className="hover:text-[var(--accent)] transition-colors">
              All Verticals
            </Link>
            <Link href="/workflows" className="hover:text-[var(--accent)] transition-colors">
              Templates
            </Link>
            <Link href="/docs" className="hover:text-[var(--accent)] transition-colors">
              Documentation
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
