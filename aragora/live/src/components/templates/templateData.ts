/**
 * TypeScript mirror of aragora/deliberation/templates/builtins.py
 * 25 templates across 8 vertical categories.
 */

export interface TemplateData {
  id: string;
  name: string;
  description: string;
  category: TemplateCategory;
  agents: string[];
  rounds: number;
  tags: string[];
  exampleTopics: string[];
}

export type TemplateCategory =
  'code' | 'legal' | 'finance' | 'healthcare' | 'compliance' | 'academic' | 'general' | 'business';

export interface CategoryMeta {
  label: string;
  icon: string;
  accent: string;
}

export const CATEGORY_META: Record<TemplateCategory, CategoryMeta> = {
  code: { label: 'CODE', icon: '</>', accent: 'acid-purple' },
  legal: { label: 'LEGAL', icon: '{}', accent: 'acid-cyan' },
  finance: { label: 'FINANCE', icon: '$', accent: 'gold' },
  healthcare: { label: 'HEALTHCARE', icon: '+', accent: 'acid-green' },
  compliance: { label: 'COMPLIANCE', icon: '%', accent: 'warning' },
  academic: { label: 'ACADEMIC', icon: '~', accent: 'acid-cyan' },
  general: { label: 'GENERAL', icon: '?', accent: 'acid-green' },
  business: { label: 'BUSINESS', icon: '#', accent: 'acid-yellow' },
};

export const TEMPLATES: TemplateData[] = [
  // Code (3)
  {
    id: 'code_review',
    name: 'Code Review',
    description: 'Multi-agent code review with security, performance, and maintainability focus',
    category: 'code',
    agents: ['anthropic-api', 'openai-api', 'codestral'],
    rounds: 3,
    tags: ['code', 'review', 'quality', 'security'],
    exampleTopics: [
      'Review this pull request for security and performance issues',
      'Check this Python module for code quality and best practices',
      'Audit this API endpoint handler for common vulnerabilities',
    ],
  },
  {
    id: 'security_audit',
    name: 'Security Audit',
    description: 'Comprehensive security audit for applications and infrastructure',
    category: 'code',
    agents: ['anthropic-api', 'openai-api', 'gemini'],
    rounds: 5,
    tags: ['security', 'audit', 'owasp', 'penetration'],
    exampleTopics: [
      'Perform a security audit of our web application',
      'Check our infrastructure for OWASP Top 10 vulnerabilities',
      'Assess the security posture of our API gateway',
    ],
  },
  {
    id: 'architecture_decision',
    name: 'Architecture Decision',
    description: 'Technical architecture decision with trade-off analysis',
    category: 'code',
    agents: ['anthropic-api', 'openai-api', 'gemini', 'mistral', 'deepseek'],
    rounds: 5,
    tags: ['architecture', 'decision', 'trade-offs', 'design'],
    exampleTopics: [
      'Should we migrate from monolith to microservices?',
      'Evaluate database options: PostgreSQL vs DynamoDB for our use case',
      'Design the architecture for a real-time event processing pipeline',
    ],
  },

  // Legal (2)
  {
    id: 'contract_review',
    name: 'Contract Review',
    description: 'Legal contract analysis with risk assessment and compliance verification',
    category: 'legal',
    agents: ['anthropic-api', 'openai-api', 'gemini'],
    rounds: 5,
    tags: ['legal', 'contracts', 'compliance', 'risk-assessment'],
    exampleTopics: [
      'Review this SaaS vendor contract for unfavorable terms',
      'Analyze the liability clauses in our partnership agreement',
      'Check this NDA for compliance with our data protection policy',
    ],
  },
  {
    id: 'due_diligence',
    name: 'Due Diligence',
    description: 'Comprehensive due diligence for M&A and investment decisions',
    category: 'legal',
    agents: ['anthropic-api', 'openai-api', 'gemini', 'mistral'],
    rounds: 7,
    tags: ['legal', 'due-diligence', 'm&a', 'investment'],
    exampleTopics: [
      'Evaluate the risks of acquiring this startup',
      'Conduct due diligence on a potential Series B investment',
      'Assess the legal and financial health of a merger target',
    ],
  },

  // Finance (2)
  {
    id: 'financial_audit',
    name: 'Financial Audit',
    description: 'Financial statement audit with multi-agent verification',
    category: 'finance',
    agents: ['anthropic-api', 'openai-api', 'gemini'],
    rounds: 5,
    tags: ['finance', 'audit', 'accounting', 'compliance'],
    exampleTopics: [
      'Audit Q3 financial statements for material misstatements',
      'Review revenue recognition practices for compliance',
      'Verify the accuracy of our annual report disclosures',
    ],
  },
  {
    id: 'risk_assessment',
    name: 'Risk Assessment',
    description: 'Enterprise risk assessment and mitigation planning',
    category: 'finance',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 4,
    tags: ['risk', 'assessment', 'mitigation', 'enterprise'],
    exampleTopics: [
      'Assess cybersecurity risks for our cloud infrastructure',
      'Evaluate supply chain risks for Q4',
      'Identify and prioritize operational risks in our expansion plan',
    ],
  },

  // Healthcare (2)
  {
    id: 'hipaa_compliance',
    name: 'HIPAA Compliance',
    description: 'HIPAA compliance verification for healthcare data handling',
    category: 'healthcare',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 4,
    tags: ['healthcare', 'hipaa', 'compliance', 'privacy'],
    exampleTopics: [
      'Verify our patient data handling meets HIPAA requirements',
      'Audit PHI access controls in our EHR system',
      'Assess HIPAA compliance of our telehealth platform',
    ],
  },
  {
    id: 'clinical_review',
    name: 'Clinical Review',
    description: 'Clinical guidelines review against evidence-based medicine',
    category: 'healthcare',
    agents: ['anthropic-api', 'openai-api', 'gemini'],
    rounds: 5,
    tags: ['healthcare', 'clinical', 'guidelines', 'evidence'],
    exampleTopics: [
      'Review treatment guidelines for Type 2 diabetes management',
      'Evaluate clinical evidence for a new cardiac intervention',
      'Assess whether this clinical protocol aligns with current best practices',
    ],
  },

  // Compliance (3)
  {
    id: 'compliance_check',
    name: 'Compliance Check',
    description: 'Regulatory compliance assessment for various frameworks',
    category: 'compliance',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 3,
    tags: ['compliance', 'regulatory', 'soc2', 'gdpr'],
    exampleTopics: [
      'Check if our data processing meets regulatory requirements',
      'Assess compliance gaps before our upcoming audit',
      'Evaluate our SOX controls for financial reporting',
    ],
  },
  {
    id: 'soc2_audit',
    name: 'SOC 2 Audit',
    description: 'SOC 2 compliance audit preparation and gap analysis',
    category: 'compliance',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 5,
    tags: ['compliance', 'soc2', 'audit', 'trust-services'],
    exampleTopics: [
      'Prepare for our SOC 2 Type II audit next quarter',
      'Identify gaps in our Trust Services Criteria controls',
      'Review our SOC 2 evidence collection process',
    ],
  },
  {
    id: 'gdpr_assessment',
    name: 'GDPR Assessment',
    description: 'GDPR compliance assessment and data protection review',
    category: 'compliance',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 4,
    tags: ['compliance', 'gdpr', 'privacy', 'data-protection'],
    exampleTopics: [
      'Assess GDPR compliance for our customer data pipeline',
      'Review our data retention policies against GDPR Article 17',
      'Evaluate our consent management implementation',
    ],
  },

  // Academic (2)
  {
    id: 'citation_verification',
    name: 'Citation Verification',
    description: 'Verify academic citations and references for accuracy',
    category: 'academic',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 3,
    tags: ['academic', 'citations', 'verification', 'research'],
    exampleTopics: [
      'Verify the citations in this research paper draft',
      'Check reference accuracy for our literature review',
      'Validate DOIs and publication details in this bibliography',
    ],
  },
  {
    id: 'peer_review',
    name: 'Peer Review',
    description: 'Multi-agent academic peer review simulation',
    category: 'academic',
    agents: ['anthropic-api', 'openai-api', 'gemini'],
    rounds: 5,
    tags: ['academic', 'peer-review', 'research', 'methodology'],
    exampleTopics: [
      'Peer review this machine learning paper submission',
      'Evaluate the methodology of this clinical trial report',
      'Assess the statistical analysis in this research manuscript',
    ],
  },

  // General + Productivity (6)
  {
    id: 'quick_decision',
    name: 'Quick Decision',
    description: 'Fast decision with minimal agents for simple questions',
    category: 'general',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 2,
    tags: ['quick', 'fast', 'simple', 'decision'],
    exampleTopics: [
      'Should we use Slack or Teams for internal communication?',
      'Is this feature worth building for our next sprint?',
      'Which cloud provider should we pick for this microservice?',
    ],
  },
  {
    id: 'research_analysis',
    name: 'Research Analysis',
    description: 'General-purpose research and analysis workflow',
    category: 'general',
    agents: ['anthropic-api', 'openai-api', 'gemini'],
    rounds: 5,
    tags: ['research', 'analysis', 'investigation'],
    exampleTopics: [
      'Research the competitive landscape for AI code review tools',
      'Analyze the impact of remote work on team productivity',
      'Investigate best practices for API versioning strategies',
    ],
  },
  {
    id: 'brainstorm',
    name: 'Brainstorm',
    description: 'Creative brainstorming with diverse agent perspectives',
    category: 'general',
    agents: ['anthropic-api', 'openai-api', 'gemini', 'mistral', 'deepseek'],
    rounds: 4,
    tags: ['brainstorm', 'creative', 'ideas', 'innovation'],
    exampleTopics: [
      'Brainstorm new features for our mobile app',
      'Generate creative marketing campaign ideas for Q2',
      'Ideate solutions for improving customer onboarding',
    ],
  },
  {
    id: 'email_prioritization',
    name: 'Email Prioritization',
    description: 'Multi-agent email triage to identify urgent and actionable messages',
    category: 'general',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 2,
    tags: ['email', 'inbox', 'triage', 'productivity'],
    exampleTopics: [
      "Prioritize my inbox for today's most urgent items",
      'Which of these emails need a response before end of day?',
      'Triage my unread emails by urgency and importance',
    ],
  },
  {
    id: 'inbox_triage',
    name: 'Inbox Triage',
    description: 'Batch email categorization and folder assignment with spam detection',
    category: 'general',
    agents: ['anthropic-api', 'openai-api', 'gemini'],
    rounds: 2,
    tags: ['email', 'categorization', 'folders', 'spam'],
    exampleTopics: [
      'Sort my inbox into categories: urgent, follow-up, FYI, spam',
      'Categorize these 50 unread emails into appropriate folders',
      'Detect and filter spam from my business inbox',
    ],
  },
  {
    id: 'meeting_prep',
    name: 'Meeting Prep',
    description: 'Prepare for meetings by analyzing relevant emails, docs, and context',
    category: 'general',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 2,
    tags: ['meeting', 'preparation', 'context', 'productivity'],
    exampleTopics: [
      "Prepare me for tomorrow's board meeting",
      'Summarize context and key topics for my 1:1 with the CTO',
      'Gather relevant docs and action items for the sprint retrospective',
    ],
  },

  // Business (6)
  {
    id: 'hiring_decision',
    name: 'Hiring Decision',
    description: 'Evaluate a hiring decision with multiple agent perspectives',
    category: 'business',
    agents: ['anthropic-api', 'openai-api', 'gemini'],
    rounds: 4,
    tags: ['business', 'hiring', 'hr', 'recruitment'],
    exampleTopics: [
      'Should we hire this VP of Engineering candidate?',
      'Evaluate the final two candidates for the product manager role',
      'Assess culture fit and technical skills for a senior hire',
    ],
  },
  {
    id: 'vendor_evaluation',
    name: 'Vendor Evaluation',
    description: 'Compare vendors for a business need',
    category: 'business',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 4,
    tags: ['business', 'vendor', 'procurement', 'comparison'],
    exampleTopics: [
      'Compare AWS vs GCP vs Azure for our infrastructure needs',
      'Evaluate CRM vendors: Salesforce vs HubSpot vs Pipedrive',
      'Assess three payment processing vendors for our e-commerce platform',
    ],
  },
  {
    id: 'budget_allocation',
    name: 'Budget Allocation',
    description: 'Debate budget allocation across departments or projects',
    category: 'business',
    agents: ['anthropic-api', 'openai-api', 'gemini'],
    rounds: 5,
    tags: ['business', 'budget', 'allocation', 'planning'],
    exampleTopics: [
      "Allocate next year's engineering budget across teams",
      'Decide how to split marketing budget between channels',
      'Prioritize R&D spending across three product lines',
    ],
  },
  {
    id: 'tool_selection',
    name: 'Tool Selection',
    description: 'Evaluate and select the best tool for a business need',
    category: 'business',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 3,
    tags: ['business', 'tools', 'selection', 'software'],
    exampleTopics: [
      'Select a project management tool for our team',
      'Choose between Jira, Linear, and Shortcut for issue tracking',
      'Evaluate CI/CD tools: GitHub Actions vs CircleCI vs Jenkins',
    ],
  },
  {
    id: 'performance_review',
    name: 'Performance Review',
    description: 'Structure performance review with multiple perspectives',
    category: 'business',
    agents: ['anthropic-api', 'openai-api'],
    rounds: 3,
    tags: ['business', 'performance', 'review', 'hr'],
    exampleTopics: [
      'Structure a fair performance review for a senior engineer',
      'Evaluate team member contributions from multiple perspectives',
      'Assess goal completion and set objectives for next quarter',
    ],
  },
  {
    id: 'strategic_planning',
    name: 'Strategic Planning',
    description: 'Evaluate strategic options for business direction',
    category: 'business',
    agents: ['anthropic-api', 'openai-api', 'gemini', 'mistral'],
    rounds: 5,
    tags: ['business', 'strategy', 'planning', 'growth'],
    exampleTopics: [
      'Should we expand into the European market this year?',
      'Evaluate strategic options for our product roadmap',
      'Plan our go-to-market strategy for the enterprise segment',
    ],
  },
];

/** Get unique categories in display order */
export const CATEGORY_ORDER: TemplateCategory[] = [
  'code',
  'business',
  'general',
  'compliance',
  'finance',
  'legal',
  'healthcare',
  'academic',
];

/** Group templates by category */
export function groupByCategory(): Map<TemplateCategory, TemplateData[]> {
  const groups = new Map<TemplateCategory, TemplateData[]>();
  for (const cat of CATEGORY_ORDER) {
    const items = TEMPLATES.filter((t) => t.category === cat);
    if (items.length > 0) groups.set(cat, items);
  }
  return groups;
}
