'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { PanelTemplate } from '@/components/shared/PanelTemplate';
import { useApi } from '@/hooks/useApi';
import { useBackend } from '@/components/BackendSelector';
import { TemplateCard, type WorkflowTemplate, type WorkflowCategory } from './TemplateCard';
import { TemplatePreview } from './TemplatePreview';
import { logger } from '@/utils/logger';

export type TemplateFilter = 'all' | WorkflowCategory;
export type TemplateSort = 'name' | 'category' | 'complexity' | 'steps';

export interface TemplateGalleryProps {
  /** Callback when a template is selected */
  onSelectTemplate?: (template: WorkflowTemplate) => void;
  /** Callback when user wants to instantiate a template */
  onInstantiate?: (template: WorkflowTemplate) => void;
  /** Show compact view */
  compact?: boolean;
  /** Custom CSS classes */
  className?: string;
}

// Mock templates matching the YAML structure
const MOCK_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'template_legal_contract_review',
    name: 'Contract Review',
    description:
      'Multi-agent review of contract documents with legal analysis, risk assessment, and compliance verification',
    version: '1.0.0',
    category: 'legal',
    tags: ['legal', 'contracts', 'review', 'compliance', 'risk-assessment'],
    steps: [
      {
        id: 'extract_terms',
        name: 'Extract Key Terms',
        step_type: 'agent',
        description: 'Extract important terms, clauses, and obligations',
      },
      {
        id: 'legal_debate',
        name: 'Legal Analysis Debate',
        step_type: 'debate',
        description: 'Multi-agent debate on legal implications',
      },
      {
        id: 'risk_assessment',
        name: 'Risk Assessment',
        step_type: 'decision',
        description: 'Evaluate risk level and route accordingly',
      },
      {
        id: 'human_review',
        name: 'Human Legal Review',
        step_type: 'human_checkpoint',
        description: 'Senior legal counsel review for high-risk contracts',
      },
      {
        id: 'senior_review',
        name: 'Senior Review',
        step_type: 'human_checkpoint',
        description: 'Senior review for medium-risk contracts',
      },
      {
        id: 'auto_approve',
        name: 'Auto-Approve',
        step_type: 'task',
        description: 'Automatically approve low-risk contracts',
      },
      {
        id: 'store_result',
        name: 'Store Analysis',
        step_type: 'memory_write',
        description: 'Store contract analysis in Knowledge Mound',
      },
    ],
    inputs: {
      document: 'Contract document to review',
      jurisdiction: 'Applicable jurisdiction (optional)',
      contract_type: 'Type of contract (optional)',
    },
    outputs: {
      analysis: 'Complete contract analysis',
      risk_score: 'Risk assessment score',
      recommendations: 'List of recommendations',
    },
    complexity: 'complex',
  },
  {
    id: 'template_legal_due_diligence',
    name: 'Due Diligence',
    description: 'Comprehensive due diligence workflow for M&A and investment decisions',
    version: '1.0.0',
    category: 'legal',
    tags: ['legal', 'due-diligence', 'm&a', 'investment', 'risk'],
    steps: [
      {
        id: 'document_collection',
        name: 'Document Collection',
        step_type: 'task',
        description: 'Gather all relevant documents',
      },
      {
        id: 'financial_analysis',
        name: 'Financial Analysis',
        step_type: 'agent',
        description: 'Analyze financial statements',
      },
      {
        id: 'legal_review',
        name: 'Legal Review',
        step_type: 'debate',
        description: 'Multi-agent legal review',
      },
      {
        id: 'risk_assessment',
        name: 'Risk Assessment',
        step_type: 'decision',
        description: 'Evaluate overall risk',
      },
      {
        id: 'report_generation',
        name: 'Generate Report',
        step_type: 'task',
        description: 'Generate final report',
      },
    ],
    inputs: {
      target_company: 'Company being evaluated',
      deal_type: 'Type of deal (M&A, investment, etc.)',
    },
    outputs: {
      report: 'Due diligence report',
      risk_rating: 'Overall risk rating',
      recommendations: 'Investment recommendations',
    },
    complexity: 'complex',
  },
  {
    id: 'template_healthcare_hipaa_compliance',
    name: 'HIPAA Compliance Check',
    description: 'Automated HIPAA compliance verification for healthcare data handling',
    version: '1.0.0',
    category: 'healthcare',
    tags: ['healthcare', 'hipaa', 'compliance', 'privacy', 'phi'],
    steps: [
      {
        id: 'data_scan',
        name: 'PHI Data Scan',
        step_type: 'agent',
        description: 'Scan for protected health information',
      },
      {
        id: 'compliance_check',
        name: 'Compliance Analysis',
        step_type: 'debate',
        description: 'Multi-agent HIPAA compliance analysis',
      },
      {
        id: 'violation_detection',
        name: 'Violation Detection',
        step_type: 'decision',
        description: 'Identify potential violations',
      },
      {
        id: 'remediation',
        name: 'Remediation Steps',
        step_type: 'human_checkpoint',
        description: 'Human review of remediation steps',
      },
      {
        id: 'audit_log',
        name: 'Audit Logging',
        step_type: 'memory_write',
        description: 'Log compliance audit results',
      },
    ],
    inputs: { data_source: 'Data source to audit', audit_scope: 'Scope of compliance check' },
    outputs: {
      compliance_score: 'HIPAA compliance score',
      violations: 'List of violations',
      remediation_plan: 'Remediation plan',
    },
    complexity: 'moderate',
  },
  {
    id: 'template_healthcare_clinical_review',
    name: 'Clinical Guidelines Review',
    description: 'Review clinical guidelines and treatment protocols against evidence',
    version: '1.0.0',
    category: 'healthcare',
    tags: ['healthcare', 'clinical', 'guidelines', 'evidence', 'treatment'],
    steps: [
      {
        id: 'evidence_gathering',
        name: 'Evidence Gathering',
        step_type: 'memory_read',
        description: 'Gather relevant clinical evidence',
      },
      {
        id: 'guideline_analysis',
        name: 'Guideline Analysis',
        step_type: 'agent',
        description: 'Analyze current guidelines',
      },
      {
        id: 'expert_debate',
        name: 'Expert Debate',
        step_type: 'debate',
        description: 'Multi-agent clinical debate',
      },
      {
        id: 'recommendation',
        name: 'Generate Recommendations',
        step_type: 'task',
        description: 'Generate treatment recommendations',
      },
    ],
    inputs: { condition: 'Medical condition', current_guidelines: 'Current treatment guidelines' },
    outputs: {
      analysis: 'Clinical analysis',
      recommendations: 'Updated recommendations',
      evidence_summary: 'Evidence summary',
    },
    complexity: 'moderate',
  },
  {
    id: 'template_accounting_financial_audit',
    name: 'Financial Audit',
    description: 'Comprehensive financial statement audit with multi-agent verification',
    version: '1.0.0',
    category: 'finance',
    tags: ['finance', 'audit', 'accounting', 'compliance', 'statements'],
    steps: [
      {
        id: 'data_extraction',
        name: 'Data Extraction',
        step_type: 'task',
        description: 'Extract financial data',
      },
      {
        id: 'anomaly_detection',
        name: 'Anomaly Detection',
        step_type: 'agent',
        description: 'Detect financial anomalies',
      },
      {
        id: 'audit_debate',
        name: 'Audit Analysis',
        step_type: 'debate',
        description: 'Multi-agent audit analysis',
      },
      {
        id: 'materiality_check',
        name: 'Materiality Assessment',
        step_type: 'decision',
        description: 'Assess materiality of findings',
      },
      {
        id: 'report',
        name: 'Audit Report',
        step_type: 'task',
        description: 'Generate audit report',
      },
    ],
    inputs: { financial_statements: 'Financial statements to audit', period: 'Audit period' },
    outputs: { audit_report: 'Audit report', findings: 'Audit findings', opinion: 'Audit opinion' },
    complexity: 'complex',
  },
  {
    id: 'template_software_code_review',
    name: 'Code Review',
    description: 'Multi-agent code review for quality, security, and best practices',
    version: '1.0.0',
    category: 'code',
    tags: ['code', 'review', 'quality', 'security', 'best-practices'],
    steps: [
      {
        id: 'static_analysis',
        name: 'Static Analysis',
        step_type: 'agent',
        description: 'Run static code analysis',
      },
      {
        id: 'security_scan',
        name: 'Security Scan',
        step_type: 'agent',
        description: 'Check for security vulnerabilities',
      },
      {
        id: 'review_debate',
        name: 'Review Discussion',
        step_type: 'debate',
        description: 'Multi-agent code review discussion',
      },
      {
        id: 'feedback',
        name: 'Generate Feedback',
        step_type: 'task',
        description: 'Generate review feedback',
      },
    ],
    inputs: { code: 'Code to review', language: 'Programming language', context: 'Code context' },
    outputs: {
      issues: 'Identified issues',
      suggestions: 'Improvement suggestions',
      quality_score: 'Code quality score',
    },
    complexity: 'moderate',
  },
  {
    id: 'template_software_security_audit',
    name: 'Security Audit',
    description: 'Comprehensive security audit for applications and infrastructure',
    version: '1.0.0',
    category: 'code',
    tags: ['security', 'audit', 'vulnerabilities', 'owasp', 'penetration'],
    steps: [
      {
        id: 'vulnerability_scan',
        name: 'Vulnerability Scan',
        step_type: 'agent',
        description: 'Automated vulnerability scanning',
      },
      {
        id: 'threat_modeling',
        name: 'Threat Modeling',
        step_type: 'debate',
        description: 'Multi-agent threat analysis',
      },
      {
        id: 'risk_rating',
        name: 'Risk Rating',
        step_type: 'decision',
        description: 'Rate security risks',
      },
      {
        id: 'human_review',
        name: 'Security Review',
        step_type: 'human_checkpoint',
        description: 'Human security expert review',
      },
      {
        id: 'report',
        name: 'Security Report',
        step_type: 'task',
        description: 'Generate security report',
      },
    ],
    inputs: { target: 'Target system or application', scope: 'Audit scope' },
    outputs: {
      vulnerabilities: 'Identified vulnerabilities',
      risk_rating: 'Overall risk rating',
      remediation: 'Remediation steps',
    },
    complexity: 'complex',
  },
  {
    id: 'template_regulatory_compliance_assessment',
    name: 'Compliance Assessment',
    description: 'Regulatory compliance assessment for various frameworks',
    version: '1.0.0',
    category: 'compliance',
    tags: ['compliance', 'regulatory', 'assessment', 'soc2', 'gdpr'],
    steps: [
      {
        id: 'framework_selection',
        name: 'Framework Selection',
        step_type: 'task',
        description: 'Select compliance frameworks',
      },
      {
        id: 'gap_analysis',
        name: 'Gap Analysis',
        step_type: 'agent',
        description: 'Identify compliance gaps',
      },
      {
        id: 'compliance_debate',
        name: 'Compliance Analysis',
        step_type: 'debate',
        description: 'Multi-agent compliance discussion',
      },
      {
        id: 'action_plan',
        name: 'Action Plan',
        step_type: 'task',
        description: 'Generate remediation plan',
      },
    ],
    inputs: { organization: 'Organization details', frameworks: 'Target compliance frameworks' },
    outputs: {
      gaps: 'Identified gaps',
      compliance_score: 'Compliance score',
      action_plan: 'Remediation action plan',
    },
    complexity: 'moderate',
  },
  {
    id: 'template_academic_citation_verification',
    name: 'Citation Verification',
    description: 'Verify academic citations and references for accuracy',
    version: '1.0.0',
    category: 'academic',
    tags: ['academic', 'citations', 'verification', 'research', 'references'],
    steps: [
      {
        id: 'extract_citations',
        name: 'Extract Citations',
        step_type: 'agent',
        description: 'Extract all citations from document',
      },
      {
        id: 'verify_sources',
        name: 'Verify Sources',
        step_type: 'agent',
        description: 'Verify citation sources',
      },
      {
        id: 'accuracy_check',
        name: 'Accuracy Check',
        step_type: 'debate',
        description: 'Multi-agent accuracy verification',
      },
      {
        id: 'report',
        name: 'Verification Report',
        step_type: 'task',
        description: 'Generate verification report',
      },
    ],
    inputs: { document: 'Academic document', citation_style: 'Citation style (APA, MLA, etc.)' },
    outputs: {
      verified_citations: 'Verified citations',
      issues: 'Citation issues',
      report: 'Verification report',
    },
    complexity: 'simple',
  },
  {
    id: 'template_general_research',
    name: 'Research Analysis',
    description: 'General-purpose research and analysis workflow',
    version: '1.0.0',
    category: 'general',
    tags: ['research', 'analysis', 'general', 'investigation'],
    steps: [
      {
        id: 'gather_info',
        name: 'Information Gathering',
        step_type: 'memory_read',
        description: 'Gather relevant information',
      },
      {
        id: 'analysis',
        name: 'Analysis',
        step_type: 'agent',
        description: 'Analyze gathered information',
      },
      {
        id: 'debate',
        name: 'Research Debate',
        step_type: 'debate',
        description: 'Multi-agent research discussion',
      },
      { id: 'synthesis', name: 'Synthesis', step_type: 'task', description: 'Synthesize findings' },
      {
        id: 'store',
        name: 'Store Results',
        step_type: 'memory_write',
        description: 'Store research results',
      },
    ],
    inputs: { topic: 'Research topic', scope: 'Research scope' },
    outputs: {
      findings: 'Research findings',
      analysis: 'Analysis summary',
      recommendations: 'Recommendations',
    },
    complexity: 'simple',
  },
];

const CATEGORIES: { id: TemplateFilter; label: string }[] = [
  { id: 'all', label: 'All Templates' },
  { id: 'legal', label: 'Legal' },
  { id: 'healthcare', label: 'Healthcare' },
  { id: 'finance', label: 'Finance' },
  { id: 'code', label: 'Software' },
  { id: 'compliance', label: 'Compliance' },
  { id: 'academic', label: 'Academic' },
  { id: 'general', label: 'General' },
];

/**
 * Workflow Template Gallery for browsing and instantiating templates.
 */
export function TemplateGallery({
  onSelectTemplate,
  onInstantiate,
  compact = false,
  className = '',
}: TemplateGalleryProps) {
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  // State
  const [templates, setTemplates] = useState<WorkflowTemplate[]>(MOCK_TEMPLATES);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<TemplateFilter>('all');
  const [sort, setSort] = useState<TemplateSort>('category');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<WorkflowTemplate | null>(null);
  const [previewTemplate, setPreviewTemplate] = useState<WorkflowTemplate | null>(null);

  // Load templates from API
  const loadTemplates = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = (await api.get('/api/workflow-templates')) as {
        templates: WorkflowTemplate[];
      };
      if (response.templates && response.templates.length > 0) {
        setTemplates(response.templates);
      }
    } catch {
      // Use mock data if API fails
      logger.warn('Using mock template data');
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  // Filter and sort templates
  const filteredTemplates = useMemo(() => {
    let result = templates;

    // Apply category filter
    if (filter !== 'all') {
      result = result.filter((t) => t.category === filter);
    }

    // Apply search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (t) =>
          t.name.toLowerCase().includes(query) ||
          t.description.toLowerCase().includes(query) ||
          t.tags.some((tag) => tag.toLowerCase().includes(query)),
      );
    }

    // Apply sort
    result = [...result].sort((a, b) => {
      switch (sort) {
        case 'name':
          return a.name.localeCompare(b.name);
        case 'category':
          return a.category.localeCompare(b.category);
        case 'complexity': {
          const order = { simple: 0, moderate: 1, complex: 2 };
          return (order[a.complexity || 'simple'] || 0) - (order[b.complexity || 'simple'] || 0);
        }
        case 'steps':
          return a.steps.length - b.steps.length;
        default:
          return 0;
      }
    });

    return result;
  }, [templates, filter, sort, searchQuery]);

  // Handle template selection
  const handleSelectTemplate = useCallback(
    (template: WorkflowTemplate) => {
      setSelectedTemplate(template);
      onSelectTemplate?.(template);
    },
    [onSelectTemplate],
  );

  // Handle instantiate
  const handleInstantiate = useCallback(
    (template: WorkflowTemplate) => {
      if (onInstantiate) {
        onInstantiate(template);
      } else {
        // Default: navigate to workflow builder with template
        router.push(`/workflows/builder?template=${template.id}`);
      }
    },
    [onInstantiate, router],
  );

  // Count by category
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: templates.length };
    templates.forEach((t) => {
      counts[t.category] = (counts[t.category] || 0) + 1;
    });
    return counts;
  }, [templates]);

  return (
    <PanelTemplate
      title="Workflow Templates"
      icon="  "
      loading={loading}
      error={error}
      onRefresh={loadTemplates}
      className={className}
      headerActions={
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as TemplateSort)}
          className="text-xs bg-surface border border-border rounded px-2 py-1 text-text"
        >
          <option value="category">By Category</option>
          <option value="name">By Name</option>
          <option value="complexity">By Complexity</option>
          <option value="steps">By Step Count</option>
        </select>
      }
    >
      {/* Search */}
      <div className="mb-4">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search templates..."
          className="w-full px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
        />
      </div>

      {/* Category filters */}
      <div className="flex flex-wrap gap-1 mb-4">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            onClick={() => setFilter(cat.id)}
            className={`px-3 py-1 text-xs font-theme-data rounded transition-colors ${
              filter === cat.id
                ? 'bg-[var(--accent)] text-bg'
                : 'bg-surface text-text-muted hover:text-text'
            }`}
          >
            {cat.label}
            {categoryCounts[cat.id] !== undefined && (
              <span className="ml-1 opacity-60">({categoryCounts[cat.id]})</span>
            )}
          </button>
        ))}
      </div>

      {/* Template grid */}
      {filteredTemplates.length === 0 ? (
        <div className="text-center py-8">
          <div className="text-4xl mb-2"> </div>
          <p className="text-text-muted">No templates found</p>
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="mt-2 text-xs text-[var(--accent)] hover:underline"
            >
              Clear search
            </button>
          )}
        </div>
      ) : (
        <div
          className={`grid gap-4 ${
            compact ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'
          }`}
        >
          {filteredTemplates.map((template) => (
            <TemplateCard
              key={template.id}
              template={template}
              selected={selectedTemplate?.id === template.id}
              onSelect={handleSelectTemplate}
              onPreview={setPreviewTemplate}
              onInstantiate={handleInstantiate}
              compact={compact}
            />
          ))}
        </div>
      )}

      {/* Results count */}
      <div className="mt-4 text-xs text-text-muted text-center">
        Showing {filteredTemplates.length} of {templates.length} templates
      </div>

      {/* Preview modal */}
      <TemplatePreview
        template={previewTemplate}
        isOpen={!!previewTemplate}
        onClose={() => setPreviewTemplate(null)}
        onInstantiate={handleInstantiate}
      />
    </PanelTemplate>
  );
}

export default TemplateGallery;
