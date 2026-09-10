'use client';

import { useEffect, useState } from 'react';
import { useOnboardingStore, type SelectedTemplate } from '@/store';
import { logger } from '@/utils/logger';

// Fallback templates when API is not available
const DEFAULT_TEMPLATES: SelectedTemplate[] = [
  {
    id: 'general/quick-decision',
    name: 'Quick Decision',
    description: 'Fast yes/no decisions with 2 agents',
    agentsCount: 2,
    rounds: 2,
    estimatedDurationMinutes: 3,
  },
  {
    id: 'product/feature-prioritization',
    name: 'Feature Prioritization',
    description: 'Prioritize features using multi-agent debate',
    agentsCount: 3,
    rounds: 3,
    estimatedDurationMinutes: 5,
  },
  {
    id: 'general/pros-cons',
    name: 'Pros and Cons Analysis',
    description: 'Balanced analysis of options',
    agentsCount: 2,
    rounds: 3,
    estimatedDurationMinutes: 4,
  },
  {
    id: 'general/deep-dive',
    name: 'Deep Dive',
    description: 'Thorough analysis with extended rounds',
    agentsCount: 3,
    rounds: 4,
    estimatedDurationMinutes: 8,
  },
];

export function TemplateSelectStep() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const {
    useCase,
    selectedTemplate,
    availableTemplates,
    setSelectedTemplate,
    setAvailableTemplates,
  } = useOnboardingStore();

  // Fetch templates from API
  useEffect(() => {
    const fetchTemplates = async () => {
      setLoading(true);
      setError(null);

      try {
        const useCaseParam = useCase || 'general';
        const response = await fetch(
          `/api/v1/templates/recommended?use_case=${useCaseParam}&limit=4`,
        );

        if (!response.ok) {
          throw new Error('Failed to fetch templates');
        }

        const data = await response.json();
        if (data.recommendations && data.recommendations.length > 0) {
          const templates = data.recommendations.map((rec: Record<string, unknown>) => ({
            id: rec.id as string,
            name: rec.name as string,
            description: rec.description as string,
            agentsCount: (rec.agents_count as number) || 2,
            rounds: (rec.rounds as number) || 3,
            estimatedDurationMinutes: (rec.estimated_duration_minutes as number) || 5,
          }));
          setAvailableTemplates(templates);
        } else {
          setAvailableTemplates(DEFAULT_TEMPLATES);
        }
      } catch (err) {
        logger.error('Failed to fetch templates:', err);
        setError('Could not load templates. Using defaults.');
        setAvailableTemplates(DEFAULT_TEMPLATES);
      } finally {
        setLoading(false);
      }
    };

    fetchTemplates();
  }, [useCase, setAvailableTemplates]);

  const templates = availableTemplates.length > 0 ? availableTemplates : DEFAULT_TEMPLATES;

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-theme-data text-[var(--accent)] mb-2">
          Choose a Debate Template
        </h3>
        <p className="text-sm text-text-muted">Select a template for your first debate</p>
      </div>

      {error && (
        <div className="px-4 py-2 bg-accent-orange/10 border border-accent-orange/30 rounded text-xs text-accent-orange">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <span className="text-text-muted font-theme-data text-sm animate-pulse">
            Loading templates...
          </span>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {templates.map((template) => (
            <button
              key={template.id}
              onClick={() => setSelectedTemplate(template)}
              className={`p-4 border rounded-lg text-left transition-all ${
                selectedTemplate?.id === template.id
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                  : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/50'
              }`}
            >
              <div
                className={`font-theme-data text-sm mb-1 ${
                  selectedTemplate?.id === template.id ? 'text-[var(--accent)]' : 'text-text'
                }`}
              >
                {template.name}
              </div>
              <div className="text-xs text-text-muted mb-3">{template.description}</div>
              <div className="flex items-center gap-4 text-xs text-text-muted">
                <span>{template.agentsCount} agents</span>
                <span>{template.rounds} rounds</span>
                <span>~{template.estimatedDurationMinutes} min</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {selectedTemplate && (
        <div className="p-4 border border-[var(--acid-cyan)]/30 rounded-lg bg-[var(--acid-cyan)]/5">
          <div className="text-sm font-theme-data text-[var(--acid-cyan)] mb-1">
            Selected: {selectedTemplate.name}
          </div>
          <div className="text-xs text-text-muted">
            This template uses {selectedTemplate.agentsCount} AI agents across{' '}
            {selectedTemplate.rounds} debate rounds.
          </div>
        </div>
      )}
    </div>
  );
}
