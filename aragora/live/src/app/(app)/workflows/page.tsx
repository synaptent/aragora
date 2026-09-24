'use client';

import { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { API_BASE_URL } from '@/config';
import { useProgressiveMode } from '@/context/ProgressiveModeContext';
import { TemplateMarketplace } from '@/components/TemplateMarketplace';
import { useWorkflows, type Workflow } from '@/hooks/useWorkflows';

interface WorkflowStep {
  id: string;
  name: string;
  type: string;
}

interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  version: string;
  tags: string[];
  steps: WorkflowStep[];
  inputs?: Record<string, string>;
  outputs?: Record<string, string>;
}

interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  category: string;
  version: string;
  tags: string[];
  stepCount: number;
  steps: WorkflowStep[];
  createdAt: string;
  updatedAt: string;
}

// Category configuration
const CATEGORIES = {
  all: {
    label: 'All Templates',
    icon: '📋',
    color: 'acid-green',
    description: 'Browse all workflow templates',
  },
  legal: {
    label: 'Legal',
    icon: '⚖️',
    color: 'purple-500',
    description: 'Contract review, due diligence, compliance',
  },
  healthcare: {
    label: 'Healthcare',
    icon: '🏥',
    color: 'green-500',
    description: 'Clinical docs, HIPAA compliance, audits',
  },
  code: {
    label: 'Software',
    icon: '💻',
    color: 'blue-500',
    description: 'Code review, security audits, CI/CD',
  },
  accounting: {
    label: 'Finance',
    icon: '📊',
    color: 'yellow-500',
    description: 'Financial audits, SOX compliance',
  },
  academic: {
    label: 'Academic',
    icon: '📚',
    color: 'indigo-500',
    description: 'Citation verification, research',
  },
  compliance: {
    label: 'Compliance',
    icon: '🛡️',
    color: 'red-500',
    description: 'GDPR, PCI-DSS, regulatory',
  },
  general: {
    label: 'General',
    icon: '🔬',
    color: 'cyan-500',
    description: 'Research, analysis, custom workflows',
  },
} as const;

type CategoryKey = keyof typeof CATEGORIES;

// Step type icons
const stepTypeIcons: Record<string, string> = {
  agent: '🤖',
  debate: '💬',
  decision: '🔀',
  parallel: '⚡',
  human_checkpoint: '👤',
  memory_write: '💾',
  memory_read: '📖',
  task: '⚙️',
};

// Use case descriptions for each template
const useCaseDescriptions: Record<
  string,
  { problem: string; solution: string; benefits: string[] }
> = {
  template_legal_contract_review: {
    problem: 'Manual contract review is slow and error-prone, missing critical risk clauses',
    solution: 'Multi-agent analysis extracts terms, debates risks, and routes by severity',
    benefits: ['70% faster review', 'Consistent risk scoring', 'Audit trail for compliance'],
  },
  template_legal_due_diligence: {
    problem: 'M&A due diligence requires coordinating multiple legal specialties',
    solution: '6 parallel review tracks synthesize into comprehensive risk report',
    benefits: ['Parallel processing', 'Cross-domain synthesis', 'Deal-ready reports'],
  },
  template_healthcare_clinical_review: {
    problem: 'Clinical documentation errors lead to coding issues and compliance risks',
    solution: 'PHI-aware review with clinical accuracy debate and coding validation',
    benefits: ['HIPAA compliant', 'Coding accuracy', 'Quality assurance'],
  },
  template_healthcare_hipaa_compliance: {
    problem: 'HIPAA compliance requires ongoing assessment across multiple rules',
    solution: 'Privacy, Security, and Breach Notification rules assessed in parallel',
    benefits: ['Comprehensive coverage', 'Gap identification', 'Remediation tracking'],
  },
  template_accounting_financial_audit: {
    problem: 'Financial audits require testing controls and substantive procedures',
    solution: 'Control testing + parallel substantive tests with materiality routing',
    benefits: ['SOX compliance', 'Materiality-based', 'Partner review workflow'],
  },
  template_software_code_review: {
    problem: 'Code reviews miss security vulnerabilities and performance issues',
    solution: '3-way parallel review: security, performance, maintainability',
    benefits: ['Security gates', 'Performance insights', 'Quality metrics'],
  },
  template_software_security_audit: {
    problem: 'Security assessments are incomplete without systematic coverage',
    solution: 'Threat modeling + 4 parallel scans with CVSS-based risk routing',
    benefits: ['CVSS scoring', 'Dependency audit', 'Critical path escalation'],
  },
  template_academic_citation_verification: {
    problem: 'Academic citations need format, source, and accuracy verification',
    solution: 'Multi-format support with parallel verification tracks',
    benefits: ['APA/MLA/Chicago', 'Source validation', 'Accuracy checks'],
  },
  template_regulatory_compliance_assessment: {
    problem: 'Multi-framework compliance (GDPR, SOX, PCI) is complex to assess',
    solution: '5 parallel domain assessments with gap analysis and remediation',
    benefits: ['Framework-agnostic', 'Gap analysis', 'Remediation plans'],
  },
  template_general_research: {
    problem: 'Research requires factual, analytical, and critical perspectives',
    solution: '3 parallel research tracks with synthesis debate',
    benefits: ['Multi-perspective', 'Quality scoring', 'Depth-configurable'],
  },
};

export default function WorkflowsPage() {
  const { isFeatureVisible } = useProgressiveMode();
  const [activeCategory, setActiveCategory] = useState<CategoryKey>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<'gallery' | 'my-workflows' | 'marketplace'>('gallery');
  const [selectedTemplate, setSelectedTemplate] = useState<WorkflowSummary | null>(null);
  const [templates, setTemplates] = useState<WorkflowSummary[]>([]);

  // Use the useWorkflows hook for CRUD operations and workflow data
  const {
    workflows: userWorkflows,
    loading: workflowsLoading,
    error: workflowsError,
    fetchTemplates: fetchWorkflowTemplates,
    deleteWorkflow,
  } = useWorkflows();

  const [templateLoading, setTemplateLoading] = useState(true);
  const [templateError, setTemplateError] = useState<string | null>(null);

  // Fetch templates via the hook, with fallback to direct fetch + demo data
  useEffect(() => {
    let cancelled = false;
    const loadTemplates = async () => {
      setTemplateLoading(true);
      try {
        // Try via the hook first
        const hookTemplates = await fetchWorkflowTemplates();
        if (!cancelled && hookTemplates.length > 0) {
          setTemplates(
            hookTemplates.map((t) => ({
              id: t.id,
              name: t.name || '',
              description: t.description || '',
              category: t.category || 'general',
              version: '1.0.0',
              tags: t.tags || [],
              stepCount: t.steps?.length || 0,
              steps: (t.steps || []).map((s) => ({
                id: s.id,
                name: s.name,
                type: s.step_type || 'task',
              })),
              createdAt: '',
              updatedAt: '',
            })),
          );
          setTemplateError(null);
        } else if (!cancelled) {
          // Fallback: try direct fetch to legacy endpoint
          const response = await fetch(`${API_BASE_URL}/api/workflow/templates`);
          if (response.ok) {
            const data = await response.json();
            const templateList: WorkflowSummary[] = (data.templates || []).map(
              (t: WorkflowTemplate) => ({
                id: t.id,
                name: t.name,
                description: t.description,
                category: t.category,
                version: t.version,
                tags: t.tags || [],
                stepCount: t.steps?.length || 0,
                steps: t.steps || [],
                createdAt: '',
                updatedAt: '',
              }),
            );
            setTemplates(templateList);
          } else {
            setTemplates(getDemoTemplates());
          }
        }
      } catch {
        if (!cancelled) {
          setTemplateError('Failed to load templates');
          setTemplates(getDemoTemplates());
        }
      } finally {
        if (!cancelled) setTemplateLoading(false);
      }
    };
    loadTemplates();
    return () => {
      cancelled = true;
    };
  }, [fetchWorkflowTemplates]);

  const loading = templateLoading || workflowsLoading;
  const error = templateError || workflowsError;

  // Filter templates by category and search
  const filteredTemplates = useMemo(() => {
    return templates.filter((t) => {
      const matchesCategory = activeCategory === 'all' || t.category === activeCategory;
      const matchesSearch =
        !searchQuery ||
        t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        t.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        t.tags.some((tag) => tag.toLowerCase().includes(searchQuery.toLowerCase()));
      return matchesCategory && matchesSearch;
    });
  }, [templates, activeCategory, searchQuery]);

  // Group templates by category for display
  const templatesByCategory = useMemo(() => {
    const grouped: Record<string, WorkflowSummary[]> = {};
    filteredTemplates.forEach((t) => {
      if (!grouped[t.category]) grouped[t.category] = [];
      grouped[t.category].push(t);
    });
    return grouped;
  }, [filteredTemplates]);

  // Category stats
  const categoryStats = useMemo(() => {
    const stats: Record<string, number> = { all: templates.length };
    templates.forEach((t) => {
      stats[t.category] = (stats[t.category] || 0) + 1;
    });
    return stats;
  }, [templates]);

  return (
    <main className="min-h-screen bg-bg">
      {/* Hero Section */}
      <div className="bg-gradient-to-b from-surface to-bg border-b border-border">
        <div className="max-w-7xl mx-auto px-6 py-12">
          <div className="flex items-start justify-between">
            <div className="max-w-2xl">
              <h1 className="text-4xl font-theme-data font-bold text-text mb-4">
                Workflow Templates
              </h1>
              <p className="text-lg text-text-muted mb-6">
                Production-ready multi-agent workflows for enterprise use cases. Each template
                orchestrates AI agents through debates, reviews, and decisions.
              </p>
              <div className="flex gap-3">
                <Link
                  href="/workflows/builder"
                  className="px-6 py-3 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors rounded flex items-center gap-2"
                >
                  <span>+</span>
                  <span>Create Custom</span>
                </Link>
                {isFeatureVisible('advanced') && (
                  <Link
                    href="/workflows/runtime"
                    className="px-6 py-3 bg-surface border border-border text-text font-theme-data hover:border-[var(--accent)] transition-colors rounded flex items-center gap-2"
                  >
                    <span>📊</span>
                    <span>View Runtime</span>
                  </Link>
                )}
              </div>
            </div>

            {/* Quick Stats */}
            <div className="hidden lg:grid grid-cols-2 gap-4">
              <div className="p-4 bg-surface border border-border rounded-lg text-center">
                <div className="text-3xl font-theme-data font-bold text-[var(--accent)]">
                  {templates.length}
                </div>
                <div className="text-xs text-text-muted font-theme-data">Templates</div>
              </div>
              <div className="p-4 bg-surface border border-border rounded-lg text-center">
                <div className="text-3xl font-theme-data font-bold text-[var(--acid-cyan)]">
                  {Object.keys(categoryStats).length - 1}
                </div>
                <div className="text-xs text-text-muted font-theme-data">Verticals</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-border bg-surface/50">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex gap-6">
            <button
              onClick={() => setActiveTab('gallery')}
              className={`py-4 font-theme-data text-sm border-b-2 transition-colors ${
                activeTab === 'gallery'
                  ? 'border-[var(--accent)] text-[var(--accent)]'
                  : 'border-transparent text-text-muted hover:text-text'
              }`}
            >
              Template Gallery
            </button>
            <button
              onClick={() => setActiveTab('my-workflows')}
              className={`py-4 font-theme-data text-sm border-b-2 transition-colors ${
                activeTab === 'my-workflows'
                  ? 'border-[var(--accent)] text-[var(--accent)]'
                  : 'border-transparent text-text-muted hover:text-text'
              }`}
            >
              My Workflows ({userWorkflows.length})
            </button>
            <button
              onClick={() => setActiveTab('marketplace')}
              className={`py-4 font-theme-data text-sm border-b-2 transition-colors ${
                activeTab === 'marketplace'
                  ? 'border-[var(--accent)] text-[var(--accent)]'
                  : 'border-transparent text-text-muted hover:text-text'
              }`}
            >
              Community Marketplace
            </button>
          </div>
        </div>
      </div>

      {activeTab === 'gallery' ? (
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="flex gap-8">
            {/* Sidebar - Categories */}
            <div className="hidden md:block w-64 shrink-0">
              <div className="sticky top-24">
                <h3 className="text-xs font-theme-data text-text-muted mb-3 uppercase tracking-wider">
                  Categories
                </h3>
                <div className="space-y-1">
                  {(
                    Object.entries(CATEGORIES) as [CategoryKey, (typeof CATEGORIES)[CategoryKey]][]
                  ).map(([key, cat]) => (
                    <button
                      key={key}
                      onClick={() => setActiveCategory(key)}
                      className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors ${
                        activeCategory === key
                          ? 'bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30'
                          : 'text-text-muted hover:text-text hover:bg-surface'
                      }`}
                    >
                      <span>{cat.icon}</span>
                      <span className="flex-1 text-sm font-theme-data">{cat.label}</span>
                      <span className="text-xs opacity-60">{categoryStats[key] || 0}</span>
                    </button>
                  ))}
                </div>

                {/* Search */}
                <div className="mt-6">
                  <h3 className="text-xs font-theme-data text-text-muted mb-3 uppercase tracking-wider">
                    Search
                  </h3>
                  <input
                    type="text"
                    placeholder="Search templates..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full px-3 py-2 bg-surface border border-border rounded text-sm font-theme-data text-text placeholder-text-muted focus:border-[var(--accent)] focus:outline-none"
                  />
                </div>

                {/* Legend */}
                <div className="mt-6 p-4 bg-surface border border-border rounded-lg">
                  <h3 className="text-xs font-theme-data text-text-muted mb-3 uppercase tracking-wider">
                    Step Types
                  </h3>
                  <div className="space-y-2 text-xs">
                    {Object.entries(stepTypeIcons)
                      .slice(0, 6)
                      .map(([type, icon]) => (
                        <div key={type} className="flex items-center gap-2 text-text-muted">
                          <span>{icon}</span>
                          <span className="capitalize">{type.replace('_', ' ')}</span>
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Main Content */}
            <div className="flex-1 min-w-0">
              {/* Mobile category selector */}
              <div className="md:hidden mb-6">
                <select
                  value={activeCategory}
                  onChange={(e) => setActiveCategory(e.target.value as CategoryKey)}
                  className="w-full px-3 py-2 bg-surface border border-border rounded text-sm font-theme-data text-text"
                >
                  {(
                    Object.entries(CATEGORIES) as [CategoryKey, (typeof CATEGORIES)[CategoryKey]][]
                  ).map(([key, cat]) => (
                    <option key={key} value={key}>
                      {cat.icon} {cat.label} ({categoryStats[key] || 0})
                    </option>
                  ))}
                </select>
              </div>

              {loading && (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-pulse text-text-muted font-theme-data">
                    Loading templates...
                  </div>
                </div>
              )}

              {error && (
                <div className="p-4 bg-warning/10 border border-warning/30 rounded-lg text-warning mb-6 text-sm">
                  {error} - Showing demo templates
                </div>
              )}

              {/* Category Header */}
              {activeCategory !== 'all' && (
                <div className="mb-6 p-4 bg-surface border border-border rounded-lg">
                  <div className="flex items-center gap-3">
                    <span className="text-3xl">{CATEGORIES[activeCategory].icon}</span>
                    <div>
                      <h2 className="text-xl font-theme-data font-bold text-text">
                        {CATEGORIES[activeCategory].label} Workflows
                      </h2>
                      <p className="text-sm text-text-muted">
                        {CATEGORIES[activeCategory].description}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Templates Grid */}
              {!loading && filteredTemplates.length === 0 ? (
                <div className="text-center py-12 bg-surface border border-border rounded-lg">
                  <div className="text-4xl mb-4">🔍</div>
                  <h3 className="text-lg font-theme-data font-bold text-text mb-2">
                    No templates found
                  </h3>
                  <p className="text-text-muted mb-4">
                    Try adjusting your search or category filter
                  </p>
                  <button
                    onClick={() => {
                      setActiveCategory('all');
                      setSearchQuery('');
                    }}
                    className="text-[var(--accent)] font-theme-data text-sm hover:underline"
                  >
                    Clear filters
                  </button>
                </div>
              ) : (
                <div className="space-y-8">
                  {activeCategory === 'all' ? (
                    // Group by category when showing all
                    Object.entries(templatesByCategory).map(([category, categoryTemplates]) => (
                      <div key={category}>
                        <h3 className="text-lg font-theme-data font-bold text-text mb-4 flex items-center gap-2">
                          <span>{CATEGORIES[category as CategoryKey]?.icon || '📁'}</span>
                          {CATEGORIES[category as CategoryKey]?.label || category}
                        </h3>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                          {categoryTemplates.map((template) => (
                            <TemplateCard
                              key={template.id}
                              template={template}
                              onSelect={() => setSelectedTemplate(template)}
                            />
                          ))}
                        </div>
                      </div>
                    ))
                  ) : (
                    // Show filtered templates
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                      {filteredTemplates.map((template) => (
                        <TemplateCard
                          key={template.id}
                          template={template}
                          onSelect={() => setSelectedTemplate(template)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : activeTab === 'my-workflows' ? (
        // My Workflows tab - populated by useWorkflows hook
        <div className="max-w-7xl mx-auto px-6 py-8">
          {userWorkflows.length === 0 ? (
            <div className="text-center py-12 bg-surface border border-border rounded-lg">
              <div className="text-4xl mb-4">📁</div>
              <h3 className="text-lg font-theme-data font-bold text-text mb-2">
                No custom workflows yet
              </h3>
              <p className="text-text-muted mb-4">Start from a template or create from scratch</p>
              <Link
                href="/workflows/builder"
                className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors rounded"
              >
                Create Workflow
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {userWorkflows.map((wf: Workflow) => {
                const summary: WorkflowSummary = {
                  id: wf.id,
                  name: wf.name,
                  description: wf.description || '',
                  category: wf.category || 'general',
                  version: String(wf.version || '1.0.0'),
                  tags: wf.tags || [],
                  stepCount: wf.steps?.length || 0,
                  steps: (wf.steps || []).map((s) => ({
                    id: s.id,
                    name: s.name,
                    type: s.step_type || 'task',
                  })),
                  createdAt: wf.created_at || '',
                  updatedAt: wf.updated_at || '',
                };
                return (
                  <div key={wf.id} className="relative group">
                    <TemplateCard
                      template={summary}
                      onSelect={() => setSelectedTemplate(summary)}
                    />
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`Delete workflow "${wf.name}"?`)) {
                          deleteWorkflow(wf.id);
                        }
                      }}
                      className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 px-2 py-1 text-xs font-theme-data bg-red-500/20 text-red-400 border border-red-500/30 rounded hover:bg-red-500/30 transition-all"
                    >
                      DELETE
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        // Community Marketplace tab
        <div className="max-w-7xl mx-auto px-6 py-8">
          <TemplateMarketplace
            onImport={(template) => {
              // Navigate to builder with imported template
              window.location.href = `/workflows/builder?import=${template.id}`;
            }}
          />
        </div>
      )}

      {/* Template Detail Modal */}
      {selectedTemplate && (
        <TemplateDetailModal
          template={selectedTemplate}
          onClose={() => setSelectedTemplate(null)}
        />
      )}

      {/* Quick Start Guide */}
      <div className="bg-surface border-t border-border mt-12">
        <div className="max-w-7xl mx-auto px-6 py-12">
          <h3 className="text-xl font-theme-data font-bold text-text mb-8 text-center">
            How It Works
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div className="text-center">
              <div className="w-12 h-12 rounded-full bg-[var(--accent)]/10 border border-[var(--accent)]/30 flex items-center justify-center mx-auto mb-4">
                <span className="text-xl">1</span>
              </div>
              <h4 className="font-theme-data font-bold text-text mb-2">Choose Template</h4>
              <p className="text-sm text-text-muted">
                Select an industry template or start from scratch
              </p>
            </div>
            <div className="text-center">
              <div className="w-12 h-12 rounded-full bg-[var(--accent)]/10 border border-[var(--accent)]/30 flex items-center justify-center mx-auto mb-4">
                <span className="text-xl">2</span>
              </div>
              <h4 className="font-theme-data font-bold text-text mb-2">Customize Steps</h4>
              <p className="text-sm text-text-muted">
                Configure agents, add checkpoints, adjust routing
              </p>
            </div>
            <div className="text-center">
              <div className="w-12 h-12 rounded-full bg-[var(--accent)]/10 border border-[var(--accent)]/30 flex items-center justify-center mx-auto mb-4">
                <span className="text-xl">3</span>
              </div>
              <h4 className="font-theme-data font-bold text-text mb-2">Execute Workflow</h4>
              <p className="text-sm text-text-muted">Run with your inputs and monitor progress</p>
            </div>
            <div className="text-center">
              <div className="w-12 h-12 rounded-full bg-[var(--accent)]/10 border border-[var(--accent)]/30 flex items-center justify-center mx-auto mb-4">
                <span className="text-xl">4</span>
              </div>
              <h4 className="font-theme-data font-bold text-text mb-2">Review Results</h4>
              <p className="text-sm text-text-muted">
                Get synthesized outputs with full audit trail
              </p>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

// Template Card Component
function TemplateCard({ template, onSelect }: { template: WorkflowSummary; onSelect: () => void }) {
  const category = CATEGORIES[template.category as CategoryKey] || CATEGORIES.general;
  const useCase = useCaseDescriptions[template.id];

  return (
    <div
      className={`
        p-5 rounded-lg border-2 transition-all cursor-pointer
        hover:scale-[1.01] hover:shadow-lg
        bg-surface border-${category.color}/30 hover:border-${category.color}
      `}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{category.icon}</span>
          <div>
            <h3 className="font-theme-data font-bold text-text">{template.name}</h3>
            <span className="text-xs text-text-muted font-theme-data capitalize">
              {template.category} • v{template.version}
            </span>
          </div>
        </div>
        <Link
          href={`/workflows/builder?template=${template.id}`}
          onClick={(e) => e.stopPropagation()}
          className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors"
        >
          Use
        </Link>
      </div>

      <p className="text-sm text-text-muted mb-4 line-clamp-2">{template.description}</p>

      {/* Step Preview */}
      <div className="flex items-center gap-1 mb-3 overflow-x-auto pb-1">
        {template.steps.slice(0, 5).map((step, i) => (
          <div key={step.id} className="flex items-center" title={step.name}>
            <span className="text-sm">{stepTypeIcons[step.type] || '⚙️'}</span>
            {i < Math.min(template.steps.length - 1, 4) && (
              <span className="text-text-muted/30 mx-0.5">→</span>
            )}
          </div>
        ))}
        {template.steps.length > 5 && (
          <span className="text-xs text-text-muted">+{template.steps.length - 5}</span>
        )}
      </div>

      {/* Tags */}
      <div className="flex flex-wrap gap-1 mb-3">
        {template.tags.slice(0, 4).map((tag) => (
          <span
            key={tag}
            className="px-2 py-0.5 text-xs bg-bg rounded font-theme-data text-text-muted"
          >
            {tag}
          </span>
        ))}
      </div>

      {/* Use Case Preview */}
      {useCase && (
        <div className="text-xs text-text-muted border-t border-border pt-3 mt-3">
          <span className="text-[var(--accent)]">✓</span> {useCase.benefits[0]}
        </div>
      )}

      <div className="flex items-center justify-between text-xs font-theme-data text-text-muted mt-2">
        <span>{template.stepCount} steps</span>
        <span className="text-[var(--accent)] hover:underline">View details →</span>
      </div>
    </div>
  );
}

// Template Detail Modal
function TemplateDetailModal({
  template,
  onClose,
}: {
  template: WorkflowSummary;
  onClose: () => void;
}) {
  const category = CATEGORIES[template.category as CategoryKey] || CATEGORIES.general;
  const useCase = useCaseDescriptions[template.id];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="bg-surface border border-border rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-6 border-b border-border">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              <span className="text-4xl">{category.icon}</span>
              <div>
                <h2 className="text-2xl font-theme-data font-bold text-text">{template.name}</h2>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs font-theme-data text-text-muted capitalize px-2 py-0.5 bg-bg rounded">
                    {template.category}
                  </span>
                  <span className="text-xs font-theme-data text-text-muted">
                    v{template.version}
                  </span>
                  <span className="text-xs font-theme-data text-text-muted">
                    {template.stepCount} steps
                  </span>
                </div>
              </div>
            </div>
            <button onClick={onClose} className="text-text-muted hover:text-text text-xl">
              ✕
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Description */}
          <div>
            <h3 className="text-sm font-theme-data font-bold text-text mb-2">Description</h3>
            <p className="text-text-muted">{template.description}</p>
          </div>

          {/* Use Case */}
          {useCase && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-theme-data font-bold text-text mb-2">Problem</h3>
                <p className="text-text-muted text-sm">{useCase.problem}</p>
              </div>
              <div>
                <h3 className="text-sm font-theme-data font-bold text-text mb-2">Solution</h3>
                <p className="text-text-muted text-sm">{useCase.solution}</p>
              </div>
              <div>
                <h3 className="text-sm font-theme-data font-bold text-text mb-2">Benefits</h3>
                <ul className="space-y-1">
                  {useCase.benefits.map((benefit, i) => (
                    <li key={i} className="text-sm text-text-muted flex items-center gap-2">
                      <span className="text-[var(--accent)]">✓</span> {benefit}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {/* Workflow Steps */}
          <div>
            <h3 className="text-sm font-theme-data font-bold text-text mb-3">Workflow Steps</h3>
            <div className="space-y-2">
              {template.steps.map((step, i) => (
                <div key={step.id} className="flex items-center gap-3 p-2 bg-bg rounded text-sm">
                  <span className="w-6 h-6 flex items-center justify-center bg-surface rounded text-xs font-theme-data text-text-muted">
                    {i + 1}
                  </span>
                  <span className="text-lg">{stepTypeIcons[step.type] || '⚙️'}</span>
                  <div className="flex-1">
                    <span className="font-theme-data text-text">{step.name}</span>
                    <span className="text-xs text-text-muted ml-2 capitalize">
                      ({step.type.replace('_', ' ')})
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Tags */}
          <div>
            <h3 className="text-sm font-theme-data font-bold text-text mb-2">Tags</h3>
            <div className="flex flex-wrap gap-2">
              {template.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-2 py-1 text-xs bg-bg rounded font-theme-data text-text-muted"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="p-6 border-t border-border flex gap-3">
          <Link
            href={`/workflows/builder?template=${template.id}`}
            className="flex-1 px-4 py-3 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors rounded text-center"
          >
            Use This Template
          </Link>
          <button
            onClick={onClose}
            className="px-4 py-3 bg-surface border border-border text-text font-theme-data hover:border-text-muted transition-colors rounded"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// Demo templates for development
function getDemoTemplates(): WorkflowSummary[] {
  return [
    {
      id: 'template_legal_contract_review',
      name: 'Contract Review',
      description: 'Multi-agent legal document analysis with risk assessment and approval routing',
      category: 'legal',
      version: '1.0.0',
      tags: ['legal', 'contracts', 'risk', 'compliance'],
      stepCount: 6,
      steps: [
        { id: '1', name: 'Extract Terms', type: 'agent' },
        { id: '2', name: 'Legal Debate', type: 'debate' },
        { id: '3', name: 'Risk Assessment', type: 'decision' },
        { id: '4', name: 'Human Review', type: 'human_checkpoint' },
        { id: '5', name: 'Store Result', type: 'memory_write' },
      ],
      createdAt: '',
      updatedAt: '',
    },
    {
      id: 'template_software_code_review',
      name: 'Code Review',
      description:
        'Multi-dimensional code review with security, performance, and maintainability analysis',
      category: 'code',
      version: '1.0.0',
      tags: ['code', 'security', 'performance', 'review'],
      stepCount: 7,
      steps: [
        { id: '1', name: 'Static Analysis', type: 'agent' },
        { id: '2', name: 'Parallel Reviews', type: 'parallel' },
        { id: '3', name: 'Synthesis Debate', type: 'debate' },
        { id: '4', name: 'Approval Decision', type: 'decision' },
        { id: '5', name: 'Summary', type: 'task' },
      ],
      createdAt: '',
      updatedAt: '',
    },
    {
      id: 'template_healthcare_hipaa_compliance',
      name: 'HIPAA Compliance',
      description:
        'Comprehensive HIPAA regulatory assessment across Privacy, Security, and Breach rules',
      category: 'healthcare',
      version: '1.0.0',
      tags: ['healthcare', 'hipaa', 'compliance', 'audit'],
      stepCount: 8,
      steps: [
        { id: '1', name: 'Privacy Rule', type: 'agent' },
        { id: '2', name: 'Security Rule', type: 'agent' },
        { id: '3', name: 'Breach Rules', type: 'agent' },
        { id: '4', name: 'Risk Analysis', type: 'debate' },
        { id: '5', name: 'Compliance Decision', type: 'decision' },
      ],
      createdAt: '',
      updatedAt: '',
    },
  ];
}
