'use client';

import type { ReactNode } from 'react';
import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAdaptiveMode } from '@/context/AdaptiveModeContext';

/**
 * Wizard step configuration
 */
export interface WizardStep {
  id: string;
  title: string;
  description: string;
  /** Component to render for this step */
  component: ReactNode;
  /** Validation function - returns error message or null if valid */
  validate?: () => string | null;
  /** Whether this step is optional */
  optional?: boolean;
  /** Only show in advanced mode */
  advancedOnly?: boolean;
}

/**
 * Use case template for quick-start wizards
 */
export interface UseCaseTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  /** Category for grouping */
  category: 'security' | 'compliance' | 'architecture' | 'research' | 'decisions';
  /** Default values for the wizard */
  defaults: Record<string, unknown>;
  /** Suggested agents for this use case */
  suggestedAgents: string[];
  /** Endpoint to call */
  endpoint: string;
  /** Number of rounds (default) */
  rounds: number;
}

/**
 * Pre-configured use case templates for quick-start
 */
export const USE_CASE_TEMPLATES: UseCaseTemplate[] = [
  {
    id: 'code-security',
    name: 'Code Security Review',
    description: 'AI-powered security analysis of your codebase',
    icon: '<',
    category: 'security',
    defaults: { auditType: 'security', depth: 'thorough' },
    suggestedAgents: ['claude-opus', 'gpt-4o', 'deepseek-v4-pro'],
    endpoint: '/api/reviews',
    rounds: 2,
  },
  {
    id: 'api-scan',
    name: 'API Vulnerability Scan',
    description: 'Test API endpoints for security vulnerabilities',
    icon: '>',
    category: 'security',
    defaults: { scanType: 'comprehensive' },
    suggestedAgents: ['claude-sonnet', 'gpt-4o', 'mistral-large'],
    endpoint: '/api/gauntlet/api',
    rounds: 3,
  },
  {
    id: 'gdpr-check',
    name: 'GDPR Compliance Check',
    description: 'Verify data protection compliance',
    icon: 'G',
    category: 'compliance',
    defaults: { framework: 'gdpr', regions: ['eu'] },
    suggestedAgents: ['claude-opus', 'gpt-4o', 'gemini-pro'],
    endpoint: '/api/gauntlet/gdpr',
    rounds: 2,
  },
  {
    id: 'hipaa-audit',
    name: 'HIPAA Audit',
    description: 'Healthcare data compliance review',
    icon: 'H',
    category: 'compliance',
    defaults: { framework: 'hipaa' },
    suggestedAgents: ['claude-opus', 'gpt-4o'],
    endpoint: '/api/gauntlet/hipaa',
    rounds: 2,
  },
  {
    id: 'stress-test',
    name: 'Decision Stress Test',
    description: 'Challenge assumptions with adversarial debate',
    icon: '%',
    category: 'architecture',
    defaults: { mode: 'adversarial', intensity: 'high' },
    suggestedAgents: ['claude-opus', 'gpt-4o', 'grok-4-latest', 'deepseek-v4-pro'],
    endpoint: '/api/gauntlet',
    rounds: 3,
  },
  {
    id: 'incident-analysis',
    name: 'Incident Root Cause',
    description: 'Analyze incidents to find root causes',
    icon: '!',
    category: 'architecture',
    defaults: { analysisType: 'root-cause' },
    suggestedAgents: ['claude-opus', 'gpt-4o', 'gemini-pro'],
    endpoint: '/api/gauntlet/incident',
    rounds: 2,
  },
  {
    id: 'research-synthesis',
    name: 'Research Synthesis',
    description: 'Synthesize insights from multiple perspectives',
    icon: '?',
    category: 'research',
    defaults: { mode: 'synthesis' },
    suggestedAgents: ['claude-opus', 'gpt-4o', 'gemini-pro', 'deepseek-v4-pro'],
    endpoint: '/api/debate',
    rounds: 3,
  },
  {
    id: 'vendor-compare',
    name: 'Vendor Comparison',
    description: 'Compare vendors with structured debate',
    icon: '[',
    category: 'decisions',
    defaults: { mode: 'matrix', format: 'comparison' },
    suggestedAgents: ['claude-opus', 'gpt-4o', 'gemini-pro'],
    endpoint: '/api/debates/matrix',
    rounds: 2,
  },
];

interface UseCaseWizardProps {
  /** Pre-selected template */
  templateId?: string;
  /** Called when wizard completes successfully */
  onComplete?: (debateId: string) => void;
  /** Called when user cancels */
  onCancel?: () => void;
  /** API base URL */
  apiBase?: string;
  /** Custom class name */
  className?: string;
}

/**
 * Multi-step wizard for creating debates based on use cases
 *
 * In Simple mode: Shows streamlined flow with auto-selected agents
 * In Advanced mode: Shows all configuration options
 */
export function UseCaseWizard({
  templateId,
  onComplete,
  onCancel,
  apiBase = '',
  className = '',
}: UseCaseWizardProps) {
  const router = useRouter();
  const { isAdvanced } = useAdaptiveMode();

  // Wizard state
  const [step, setStep] = useState<'select' | 'configure' | 'review' | 'running'>('select');
  const [selectedTemplate, setSelectedTemplate] = useState<UseCaseTemplate | null>(
    templateId ? USE_CASE_TEMPLATES.find((t) => t.id === templateId) || null : null,
  );
  const [formData, setFormData] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Form field updates
  const updateField = useCallback((key: string, value: unknown) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  }, []);

  // Select template and advance
  const handleSelectTemplate = useCallback((template: UseCaseTemplate) => {
    setSelectedTemplate(template);
    setFormData({
      ...template.defaults,
      agents: template.suggestedAgents.join(','),
      rounds: template.rounds,
    });
    setStep('configure');
  }, []);

  // Go back to previous step
  const handleBack = useCallback(() => {
    if (step === 'configure') setStep('select');
    else if (step === 'review') setStep('configure');
  }, [step]);

  // Advance to next step
  const handleNext = useCallback(() => {
    if (step === 'configure') setStep('review');
  }, [step]);

  // Submit the wizard
  const handleSubmit = useCallback(async () => {
    if (!selectedTemplate) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const response = await fetch(`${apiBase}${selectedTemplate.endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...selectedTemplate.defaults,
          ...formData,
          metadata: { template: selectedTemplate.id, wizard: true },
        }),
      });

      const data = await response.json();

      if (data.success && (data.debate_id || data.review_id || data.gauntlet_id)) {
        const id = data.debate_id || data.review_id || data.gauntlet_id;
        if (onComplete) {
          onComplete(id);
        } else {
          // Navigate to appropriate page
          if (selectedTemplate.category === 'security' && data.review_id) {
            router.push(`/reviews/${id}`);
          } else {
            router.push(`/debate/${id}`);
          }
        }
      } else {
        setError(data.error || 'Failed to start. Please try again.');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  }, [selectedTemplate, formData, apiBase, onComplete, router]);

  return (
    <div className={`border border-[var(--accent)]/30 bg-surface ${className}`}>
      {/* Header */}
      <div className="border-b border-[var(--accent)]/20 px-4 py-3 flex items-center justify-between">
        <div>
          <h2 className="text-text font-bold font-theme-data">
            {step === 'select' && 'Select Use Case'}
            {step === 'configure' && selectedTemplate?.name}
            {step === 'review' && 'Review & Start'}
            {step === 'running' && 'Running...'}
          </h2>
          <p className="text-text-muted text-sm mt-1">
            {step === 'select' && 'Choose a template to get started quickly'}
            {step === 'configure' && selectedTemplate?.description}
            {step === 'review' && 'Confirm your settings before starting'}
            {step === 'running' && 'Your debate is being created'}
          </p>
        </div>
        {onCancel && step !== 'running' && (
          <button
            onClick={onCancel}
            className="text-text-muted hover:text-text transition-colors"
            aria-label="Close wizard"
          >
            &times;
          </button>
        )}
      </div>

      {/* Progress indicator */}
      <div className="px-4 py-2 border-b border-[var(--accent)]/10 flex items-center gap-2">
        {['select', 'configure', 'review'].map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <div
              className={`
                w-6 h-6 rounded-full flex items-center justify-center
                font-theme-data text-xs
                ${
                  step === s
                    ? 'bg-[var(--accent)] text-bg'
                    : ['select', 'configure', 'review'].indexOf(step) > i
                      ? 'bg-[var(--accent)]/30 text-[var(--accent)]'
                      : 'bg-surface border border-[var(--accent)]/30 text-text-muted'
                }
              `}
            >
              {i + 1}
            </div>
            {i < 2 && (
              <div
                className={`w-8 h-0.5 ${
                  ['select', 'configure', 'review'].indexOf(step) > i
                    ? 'bg-[var(--accent)]/50'
                    : 'bg-[var(--accent)]/20'
                }`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Content */}
      <div className="p-4">
        {/* Error message */}
        {error && (
          <div className="mb-4 p-3 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 text-[var(--crimson)] text-sm">
            {error}
          </div>
        )}

        {/* Step: Select template */}
        {step === 'select' && (
          <TemplateSelector templates={USE_CASE_TEMPLATES} onSelect={handleSelectTemplate} />
        )}

        {/* Step: Configure */}
        {step === 'configure' && selectedTemplate && (
          <ConfigureStep
            template={selectedTemplate}
            formData={formData}
            updateField={updateField}
            isAdvanced={isAdvanced}
          />
        )}

        {/* Step: Review */}
        {step === 'review' && selectedTemplate && (
          <ReviewStep template={selectedTemplate} formData={formData} />
        )}

        {/* Step: Running */}
        {step === 'running' && (
          <div className="py-8 text-center">
            <div className="text-[var(--accent)] font-theme-data text-lg animate-pulse">
              INITIALIZING...
            </div>
            <p className="text-text-muted text-sm mt-2">
              Please wait while we set up your {selectedTemplate?.name?.toLowerCase()}
            </p>
          </div>
        )}
      </div>

      {/* Footer with navigation */}
      {step !== 'running' && (
        <div className="border-t border-[var(--accent)]/20 px-4 py-3 flex items-center justify-between">
          <div>
            {step !== 'select' && (
              <button
                onClick={handleBack}
                className="px-3 py-1.5 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                [BACK]
              </button>
            )}
          </div>
          <div>
            {step === 'configure' && (
              <button
                onClick={handleNext}
                className="px-4 py-1.5 bg-[var(--accent)]/10 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/20 transition-colors"
              >
                [NEXT]
              </button>
            )}
            {step === 'review' && (
              <button
                onClick={handleSubmit}
                disabled={isSubmitting}
                className={`
                  px-4 py-1.5 font-theme-data text-sm transition-colors
                  ${
                    isSubmitting
                      ? 'bg-[var(--accent)]/20 text-[var(--accent)]/50 cursor-wait'
                      : 'bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/90'
                  }
                `}
              >
                {isSubmitting ? '[STARTING...]' : '[START]'}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Template selection grid
 */
function TemplateSelector({
  templates,
  onSelect,
}: {
  templates: UseCaseTemplate[];
  onSelect: (template: UseCaseTemplate) => void;
}) {
  // Group templates by category
  const grouped = templates.reduce(
    (acc, t) => {
      if (!acc[t.category]) acc[t.category] = [];
      acc[t.category].push(t);
      return acc;
    },
    {} as Record<string, UseCaseTemplate[]>,
  );

  const categoryLabels: Record<string, string> = {
    security: 'Security',
    compliance: 'Compliance',
    architecture: 'Architecture',
    research: 'Research',
    decisions: 'Decisions',
  };

  return (
    <div className="space-y-6">
      {Object.entries(grouped).map(([category, categoryTemplates]) => (
        <div key={category}>
          <h3 className="text-[var(--acid-cyan)] text-xs uppercase tracking-wider mb-2">
            {categoryLabels[category]}
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {categoryTemplates.map((template) => (
              <button
                key={template.id}
                onClick={() => onSelect(template)}
                className="
                  p-3 text-left border border-[var(--accent)]/30
                  hover:border-[var(--accent)]/50 hover:bg-[var(--accent)]/5
                  transition-colors rounded
                "
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[var(--accent)] font-theme-data">{template.icon}</span>
                  <span className="font-theme-data font-bold text-text">{template.name}</span>
                </div>
                <p className="text-xs text-text-muted">{template.description}</p>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Configuration step
 */
function ConfigureStep({
  template,
  formData,
  updateField,
  isAdvanced,
}: {
  template: UseCaseTemplate;
  formData: Record<string, unknown>;
  updateField: (key: string, value: unknown) => void;
  isAdvanced: boolean;
}) {
  return (
    <div className="space-y-4">
      {/* Primary input - always shown */}
      <div>
        <label className="block text-sm font-theme-data text-text-muted mb-1">
          Question / Topic
        </label>
        <textarea
          value={(formData.question as string) || ''}
          onChange={(e) => updateField('question', e.target.value)}
          placeholder={`What would you like to ${template.category === 'security' ? 'review' : 'analyze'}?`}
          className="
            w-full px-3 py-2 bg-bg border border-[var(--accent)]/30
            text-text font-theme-data text-sm
            focus:border-[var(--accent)] focus:outline-none
            resize-none
          "
          rows={3}
        />
      </div>

      {/* Agent selection - simplified in simple mode */}
      <div>
        <label className="block text-sm font-theme-data text-text-muted mb-1">AI Agents</label>
        {isAdvanced ? (
          <input
            type="text"
            value={(formData.agents as string) || ''}
            onChange={(e) => updateField('agents', e.target.value)}
            placeholder="claude-opus,gpt-4o,gemini-pro"
            className="
              w-full px-3 py-2 bg-bg border border-[var(--accent)]/30
              text-text font-theme-data text-sm
              focus:border-[var(--accent)] focus:outline-none
            "
          />
        ) : (
          <div className="px-3 py-2 bg-[var(--accent)]/5 border border-[var(--accent)]/20 text-sm">
            <span className="text-[var(--accent)] font-theme-data">
              {template.suggestedAgents.length} agents selected
            </span>
            <span className="text-text-muted ml-2">(recommended for this use case)</span>
          </div>
        )}
      </div>

      {/* Rounds - only in advanced mode */}
      {isAdvanced && (
        <div>
          <label className="block text-sm font-theme-data text-text-muted mb-1">
            Debate Rounds
          </label>
          <input
            type="number"
            min={1}
            max={10}
            value={(formData.rounds as number) || template.rounds}
            onChange={(e) => updateField('rounds', parseInt(e.target.value, 10))}
            className="
              w-24 px-3 py-2 bg-bg border border-[var(--accent)]/30
              text-text font-theme-data text-sm
              focus:border-[var(--accent)] focus:outline-none
            "
          />
        </div>
      )}

      {/* File upload hint */}
      <div className="p-3 bg-surface border border-[var(--accent)]/10 rounded">
        <p className="text-xs text-text-muted">
          <span className="text-[var(--acid-cyan)]">[TIP]</span> You can also upload files for
          analysis from the Documents page or drag-and-drop after starting.
        </p>
      </div>
    </div>
  );
}

/**
 * Review step before submission
 */
function ReviewStep({
  template,
  formData,
}: {
  template: UseCaseTemplate;
  formData: Record<string, unknown>;
}) {
  return (
    <div className="space-y-4">
      <div className="p-4 bg-surface border border-[var(--accent)]/20 rounded">
        <h4 className="font-theme-data text-[var(--accent)] mb-3">Summary</h4>
        <dl className="space-y-2 text-sm">
          <div className="flex">
            <dt className="text-text-muted w-24">Template:</dt>
            <dd className="text-text font-theme-data">{template.name}</dd>
          </div>
          <div className="flex">
            <dt className="text-text-muted w-24">Question:</dt>
            <dd className="text-text">{(formData.question as string) || '(not specified)'}</dd>
          </div>
          <div className="flex">
            <dt className="text-text-muted w-24">Agents:</dt>
            <dd className="text-text font-theme-data">{formData.agents as string}</dd>
          </div>
          <div className="flex">
            <dt className="text-text-muted w-24">Rounds:</dt>
            <dd className="text-text font-theme-data">{formData.rounds as number}</dd>
          </div>
        </dl>
      </div>

      <p className="text-xs text-text-muted text-center">
        Click [START] to begin. You&apos;ll be redirected to view the results.
      </p>
    </div>
  );
}

/**
 * Compact use case selector for landing pages
 */
export function UseCaseQuickSelect({
  onSelect,
  className = '',
}: {
  onSelect: (templateId: string) => void;
  className?: string;
}) {
  const quickTemplates = USE_CASE_TEMPLATES.slice(0, 4);

  return (
    <div className={`grid grid-cols-2 sm:grid-cols-4 gap-2 ${className}`}>
      {quickTemplates.map((template) => (
        <button
          key={template.id}
          onClick={() => onSelect(template.id)}
          className="
            p-3 border border-[var(--accent)]/30 rounded
            hover:border-[var(--accent)]/50 hover:bg-[var(--accent)]/5
            transition-colors text-center
          "
        >
          <div className="text-[var(--accent)] font-theme-data text-2xl mb-1">{template.icon}</div>
          <div className="text-xs font-theme-data text-text">{template.name}</div>
        </button>
      ))}
    </div>
  );
}
