/**
 * About Page Constants
 *
 * Static data and content for the About page.
 */

// =============================================================================
// Types
// =============================================================================

export interface UseCase {
  icon: string;
  title: string;
  subtitle: string;
  examples: string[];
}

export interface DocLink {
  name: string;
  href: string;
}

export interface DocCategory {
  title: string;
  icon: string;
  docs: DocLink[];
}

export interface Capability {
  label: string;
  value: string;
  desc: string;
}

// =============================================================================
// Use Cases - What Aragora can do
// =============================================================================

export const USE_CASES: UseCase[] = [
  {
    icon: '🏗️',
    title: 'Architecture Stress-Test',
    subtitle: 'Find critical flaws before launch',
    examples: [
      'Identify scaling bottlenecks and single points of failure',
      'Validate infrastructure for 10x traffic scenarios',
    ],
  },
  {
    icon: '🔐',
    title: 'API Security Review',
    subtitle: 'AI red-team your endpoints',
    examples: [
      'Detect BOLA, injection, and access control issues',
      'Find rate limiting gaps and data exposure risks',
    ],
  },
  {
    icon: '📋',
    title: 'Compliance Audit',
    subtitle: 'GDPR, HIPAA, SOC 2 readiness',
    examples: [
      'Persona-based compliance checks with CFR citations',
      'Audit-ready transcripts with minority views preserved',
    ],
  },
  {
    icon: '🔍',
    title: 'Code Review',
    subtitle: 'Multi-model adversarial analysis',
    examples: [
      'Security vulnerabilities, logic errors, edge cases',
      'Cross-model consensus on critical issues',
    ],
  },
  {
    icon: '🔥',
    title: 'Incident Response',
    subtitle: 'Red-team RCA and mitigations',
    examples: [
      'Root cause analysis with competing hypotheses',
      'Mitigation strategies stress-tested by adversarial agents',
    ],
  },
  {
    icon: '⚖️',
    title: 'Decision Making',
    subtitle: 'Defensible decisions with receipts',
    examples: [
      'Decision transcripts with dissenting views recorded',
      'Confidence scores and evidence chains for audit',
    ],
  },
  {
    icon: '🏥',
    title: 'Healthcare Decisions',
    subtitle: 'Multi-agent clinical reasoning',
    examples: [
      'Evidence-grounded treatment recommendations',
      'HIPAA-compliant audit trails with PHI redaction',
    ],
  },
  {
    icon: '📊',
    title: 'Financial Analysis',
    subtitle: 'Investment due diligence',
    examples: [
      'Multi-model risk assessment and stress testing',
      'Adversarial analysis of investment theses',
    ],
  },
  {
    icon: '🔬',
    title: 'Research Synthesis',
    subtitle: 'Literature review at scale',
    examples: [
      'Cross-paper consensus with citation verification',
      'Scholarly evidence grounding and provenance',
    ],
  },
  {
    icon: '📝',
    title: 'Contract Negotiation',
    subtitle: 'Adversarial clause analysis',
    examples: ['Multi-agent risk identification', 'Precedent recall from organizational memory'],
  },
  {
    icon: '🐛',
    title: 'Software QA & Debugging',
    subtitle: 'Root cause analysis at scale',
    examples: [
      'Multi-agent hypothesis testing for bug isolation',
      'Test coverage gaps and regression detection',
    ],
  },
  {
    icon: '🧮',
    title: 'Accounting Reconciliation',
    subtitle: 'Transaction verification',
    examples: [
      "Benford's Law fraud detection and anomaly flagging",
      'Journal entry balance verification and duplicate detection',
    ],
  },
  {
    icon: '🏪',
    title: 'Vendor Evaluation',
    subtitle: 'Multi-criteria comparison',
    examples: [
      'Scenario matrix testing across constraints',
      'Weighted evaluation with adversarial stress testing',
    ],
  },
  {
    icon: '🔎',
    title: 'Discrepancy Detection',
    subtitle: 'Cross-document consistency',
    examples: [
      'Number, date, and definition drift across versions',
      'Specification conflicts and calculation errors',
    ],
  },
  {
    icon: '📑',
    title: 'Regulatory Filings',
    subtitle: 'SOX, GDPR, PCI-DSS verification',
    examples: ['Control requirement pattern matching', 'Multi-framework compliance gap analysis'],
  },
  {
    icon: '⚙️',
    title: 'Business Process Audit',
    subtitle: 'Workflow and control review',
    examples: [
      'Approval chain gaps and segregation of duties',
      'Control deficiency tracking with remediation',
    ],
  },
];

// =============================================================================
// Document Library Categories
// =============================================================================

export const DOC_CATEGORIES: DocCategory[] = [
  {
    title: 'Getting Started',
    icon: '🚀',
    docs: [
      { name: 'Quick Start', href: '/developer#quickstart' },
      { name: 'Installation', href: '/developer#getting-started' },
      { name: 'CLI Reference', href: '/developer#cli' },
    ],
  },
  {
    title: 'Core Features',
    icon: '⚙️',
    docs: [
      { name: 'Nomic Loop', href: '/developer#nomic-loop' },
      { name: 'Gauntlet', href: '/developer#gauntlet' },
      { name: 'Graph Debates', href: '/developer#graph-debates' },
      { name: 'Matrix Debates', href: '/developer#matrix-debates' },
    ],
  },
  {
    title: 'API & Integration',
    icon: '🔌',
    docs: [
      { name: 'API Reference', href: '/developer#api' },
      { name: 'API Examples', href: '/developer#api-examples' },
      { name: 'TypeScript SDK', href: '/developer#sdk' },
    ],
  },
  {
    title: 'Agent Development',
    icon: '🤖',
    docs: [
      { name: 'Custom Agents', href: '/developer#custom-agents' },
      { name: 'Agent Selection', href: '/developer#agent-selection' },
      { name: 'Formal Verification', href: '/developer#verification' },
    ],
  },
  {
    title: 'Deployment',
    icon: '🚢',
    docs: [
      { name: 'Deployment Guide', href: '/developer#deployment' },
      { name: 'Production Checklist', href: '/developer#production' },
      { name: 'Scaling', href: '/developer#scaling' },
    ],
  },
  {
    title: 'Security',
    icon: '🔒',
    docs: [
      { name: 'Security Guide', href: '/developer#security' },
      { name: 'Compliance', href: '/developer#compliance' },
      { name: 'Security Patterns', href: '/developer#security-patterns' },
    ],
  },
];

// =============================================================================
// Platform Capabilities
// =============================================================================

export const CAPABILITIES: Capability[] = [
  {
    label: 'AI Providers',
    value: '20+',
    desc: 'Claude, GPT, Gemini, Mistral, Grok, DeepSeek, Qwen, Kimi, Llama...',
  },
  {
    label: 'Consensus Algorithms',
    value: '8',
    desc: 'Majority, unanimous, judge, weighted, supermajority, any, byzantine, none',
  },
  { label: 'Debate Types', value: '3', desc: 'Standard, graph, matrix' },
  { label: 'Memory Tiers', value: '4', desc: 'Fast, medium, slow, glacial' },
  { label: 'REST Endpoints', value: '987+', desc: 'Full API coverage' },
  { label: 'Tests', value: '43,500+', desc: 'Comprehensive coverage' },
  {
    label: 'Data Connectors',
    value: '24',
    desc: 'GitHub, S3, SharePoint, FHIR, PostgreSQL, ArXiv, Confluence...',
  },
  {
    label: 'WebSocket Events',
    value: '80+',
    desc: 'Real-time streaming with audience participation',
  },
  { label: 'Compliance Presets', value: '5', desc: 'GDPR, HIPAA, SOX, AI Act, Security gauntlets' },
  { label: 'API Handlers', value: '182', desc: 'Modular endpoint handlers' },
];
