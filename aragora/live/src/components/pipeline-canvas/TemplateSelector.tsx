'use client';

import { memo, useState, useEffect, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';
import { joinBackendPath } from '@/lib/backendUrls';

// =============================================================================
// Types
// =============================================================================

interface PipelineTemplate {
  name: string;
  display_name: string;
  description: string;
  category: string;
  idea_count: number;
  tags: string[];
  vertical_profile: string | null;
}

interface TemplateSelectorProps {
  onSelectTemplate: (templateName: string) => void;
  onStartBlank: () => void;
}

const CATEGORY_ICONS: Record<string, string> = {
  people: 'U',
  product: 'P',
  compliance: 'C',
  strategy: 'S',
  procurement: 'V',
};

const CATEGORY_COLORS: Record<string, string> = {
  people: 'border-indigo-500 bg-indigo-500/10',
  product: 'border-emerald-500 bg-emerald-500/10',
  compliance: 'border-amber-500 bg-amber-500/10',
  strategy: 'border-pink-500 bg-pink-500/10',
  procurement: 'border-cyan-500 bg-cyan-500/10',
};

// =============================================================================
// Component
// =============================================================================

export const TemplateSelector = memo(function TemplateSelector({
  onSelectTemplate,
  onStartBlank,
}: TemplateSelectorProps) {
  const { config: backendConfig } = useBackend();
  const [templates, setTemplates] = useState<PipelineTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchTemplates() {
      try {
        const res = await fetch(
          joinBackendPath(backendConfig.api, '/api/v1/canvas/pipeline/templates'),
        );
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) {
            setTemplates(data.templates || []);
          }
        }
      } catch {
        // Fallback: use hardcoded template list
        if (!cancelled) {
          setTemplates([
            {
              name: 'hiring_decision',
              display_name: 'Hiring Decision',
              description: 'Evaluate candidates with diverse agent perspectives.',
              category: 'people',
              idea_count: 6,
              tags: ['hr', 'hiring'],
              vertical_profile: null,
            },
            {
              name: 'product_launch',
              display_name: 'Product Launch',
              description: 'Market analysis, go/no-go decision, and launch plan.',
              category: 'product',
              idea_count: 7,
              tags: ['product', 'launch'],
              vertical_profile: null,
            },
            {
              name: 'compliance_audit',
              display_name: 'Compliance Audit',
              description: 'Regulation review, gap analysis, and remediation.',
              category: 'compliance',
              idea_count: 6,
              tags: ['compliance', 'audit'],
              vertical_profile: 'compliance_sox',
            },
            {
              name: 'market_entry',
              display_name: 'Market Entry Strategy',
              description: 'Competitive analysis, strategy, and execution roadmap.',
              category: 'strategy',
              idea_count: 7,
              tags: ['strategy', 'market'],
              vertical_profile: null,
            },
            {
              name: 'vendor_selection',
              display_name: 'Vendor Selection',
              description: 'Requirements, evaluation criteria, and selection.',
              category: 'procurement',
              idea_count: 7,
              tags: ['procurement', 'vendor'],
              vertical_profile: null,
            },
          ]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchTemplates();
    return () => {
      cancelled = true;
    };
  }, [backendConfig.api]);

  const categories = Array.from(new Set(templates.map((t) => t.category)));
  const filtered = selectedCategory
    ? templates.filter((t) => t.category === selectedCategory)
    : templates;

  const handleSelect = useCallback(
    (name: string) => {
      onSelectTemplate(name);
    },
    [onSelectTemplate],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-text-muted font-theme-data text-sm">Loading templates...</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-full p-8 max-w-4xl mx-auto">
      <h2 className="text-lg font-theme-data font-bold text-text uppercase tracking-wide mb-2">
        Start a Pipeline
      </h2>
      <p className="text-sm text-text-muted mb-6 text-center">
        Choose a template to pre-populate your pipeline, or start from scratch.
      </p>

      {/* Category filter */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setSelectedCategory(null)}
          className={`px-3 py-1 rounded font-theme-data text-xs transition-colors ${
            !selectedCategory
              ? 'bg-surface text-text ring-1 ring-acid-green'
              : 'text-text-muted hover:text-text hover:bg-surface/50'
          }`}
        >
          All
        </button>
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setSelectedCategory(cat === selectedCategory ? null : cat)}
            className={`px-3 py-1 rounded font-theme-data text-xs capitalize transition-colors ${
              cat === selectedCategory
                ? 'bg-surface text-text ring-1 ring-acid-green'
                : 'text-text-muted hover:text-text hover:bg-surface/50'
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* Template grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 w-full mb-6">
        {filtered.map((template) => (
          <div
            key={template.name}
            className={`rounded-lg border-2 p-4 cursor-pointer transition-all duration-200 hover:scale-[1.02] hover:shadow-lg ${
              CATEGORY_COLORS[template.category] || 'border-border bg-surface/50'
            }`}
            onClick={() => handleSelect(template.name)}
          >
            <div className="flex items-start gap-3 mb-2">
              <div className="w-8 h-8 rounded bg-surface flex items-center justify-center font-theme-data text-sm font-bold text-text">
                {CATEGORY_ICONS[template.category] || '?'}
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-sm font-theme-data font-bold text-text truncate">
                  {template.display_name}
                </h3>
                <span className="text-xs font-theme-data text-text-muted capitalize">
                  {template.category}
                </span>
              </div>
            </div>
            <p className="text-xs text-text-muted mb-3 line-clamp-2">{template.description}</p>
            <div className="flex items-center justify-between">
              <span className="text-xs font-theme-data text-text-muted">
                {template.idea_count} ideas
              </span>
              <button
                className="px-3 py-1 bg-surface border border-border text-text font-theme-data text-xs rounded hover:bg-bg transition-colors"
                onClick={(e) => {
                  e.stopPropagation();
                  handleSelect(template.name);
                }}
              >
                Use Template
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Blank pipeline option */}
      <button
        onClick={onStartBlank}
        className="px-6 py-3 border-2 border-dashed border-border rounded-lg text-text-muted font-theme-data text-sm hover:border-[var(--accent)] hover:text-text transition-colors"
      >
        Blank Pipeline &mdash; Start from scratch
      </button>
    </div>
  );
});

export default TemplateSelector;
