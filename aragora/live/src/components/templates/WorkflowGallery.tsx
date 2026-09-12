'use client';

import { useState, useMemo } from 'react';
import { TEMPLATES, CATEGORY_META, type TemplateData, type TemplateCategory } from './templateData';

interface WorkflowGalleryProps {
  /** Callback when user selects a template to run */
  onSelectTemplate?: (template: TemplateData) => void;
  /** Pre-selected category filter */
  initialCategory?: TemplateCategory;
}

function TemplateCard({
  template,
  onSelect,
}: {
  template: TemplateData;
  onSelect?: (t: TemplateData) => void;
}) {
  const meta = CATEGORY_META[template.category];

  return (
    <div className="p-4 border border-border rounded-lg bg-surface/50 hover:border-[var(--accent)]/40 transition-colors group">
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className={`text-xs font-theme-data px-1.5 py-0.5 rounded border border-${meta.accent}/30 text-${meta.accent} bg-${meta.accent}/10`}
          >
            {meta.icon} {meta.label}
          </span>
        </div>
        <span className="text-xs font-theme-data text-text-muted">
          {template.rounds}R / {template.agents.length}A
        </span>
      </div>

      <h4 className="text-sm font-theme-data text-text mb-1 group-hover:text-[var(--accent)] transition-colors">
        {template.name}
      </h4>
      <p className="text-xs text-text-muted line-clamp-2 mb-3">{template.description}</p>

      {/* Tags */}
      <div className="flex gap-1 flex-wrap mb-3">
        {template.tags.slice(0, 4).map((tag) => (
          <span
            key={tag}
            className="text-xs font-theme-data px-1.5 py-0.5 bg-bg rounded text-text-muted"
          >
            {tag}
          </span>
        ))}
      </div>

      {/* Agents */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          {template.agents.slice(0, 3).map((agent) => (
            <span
              key={agent}
              className="text-xs font-theme-data px-1 py-0.5 border border-border rounded text-text-muted"
              title={agent}
            >
              {agent.split('-')[0]}
            </span>
          ))}
          {template.agents.length > 3 && (
            <span className="text-xs text-text-muted">+{template.agents.length - 3}</span>
          )}
        </div>

        {onSelect && (
          <button
            onClick={() => onSelect(template)}
            className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30 rounded hover:bg-[var(--accent)]/20 opacity-0 group-hover:opacity-100 transition-all"
          >
            Use Template
          </button>
        )}
      </div>

      {/* Example topics (shown on hover) */}
      {template.exampleTopics.length > 0 && (
        <div className="mt-3 pt-3 border-t border-border hidden group-hover:block">
          <div className="text-xs font-theme-data text-text-muted mb-1">Example topics:</div>
          {template.exampleTopics.slice(0, 2).map((topic, i) => (
            <div key={i} className="text-xs text-text-muted/70 truncate">
              &gt; {topic}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Workflow template gallery for browsing and selecting pre-built debate/workflow templates.
 * Shows templates organized by category with search and filtering.
 */
export function WorkflowGallery({ onSelectTemplate, initialCategory }: WorkflowGalleryProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<TemplateCategory | 'all'>(
    initialCategory ?? 'all',
  );

  // Category counts
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: TEMPLATES.length };
    for (const t of TEMPLATES) {
      counts[t.category] = (counts[t.category] || 0) + 1;
    }
    return counts;
  }, []);

  // Filter templates
  const filteredTemplates = useMemo(() => {
    let results = TEMPLATES;

    if (selectedCategory !== 'all') {
      results = results.filter((t) => t.category === selectedCategory);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      results = results.filter(
        (t) =>
          t.name.toLowerCase().includes(q) ||
          t.description.toLowerCase().includes(q) ||
          t.tags.some((tag) => tag.includes(q)),
      );
    }

    return results;
  }, [selectedCategory, searchQuery]);

  // Group by category for gallery view
  const grouped = useMemo(() => {
    if (selectedCategory !== 'all') return null;

    const groups: Record<string, TemplateData[]> = {};
    for (const t of filteredTemplates) {
      (groups[t.category] ??= []).push(t);
    }
    return groups;
  }, [selectedCategory, filteredTemplates]);

  const categories = Object.keys(CATEGORY_META) as TemplateCategory[];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-theme-data text-[var(--accent)]">Workflow Templates</h2>
          <p className="text-xs text-text-muted font-theme-data">
            {TEMPLATES.length} templates across {categories.length} categories
          </p>
        </div>
      </div>

      {/* Search */}
      <input
        type="text"
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        placeholder="Search templates by name, description, or tag..."
        className="w-full px-3 py-2 bg-bg border border-border rounded text-sm text-text placeholder-text-muted font-theme-data focus:border-[var(--accent)] focus:outline-none"
      />

      {/* Category filters */}
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => setSelectedCategory('all')}
          className={`px-3 py-1.5 text-xs font-theme-data border rounded transition-colors ${
            selectedCategory === 'all'
              ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
              : 'border-border text-text-muted hover:border-[var(--accent)]/30'
          }`}
        >
          ALL ({categoryCounts.all})
        </button>
        {categories.map((cat) => {
          const meta = CATEGORY_META[cat];
          const count = categoryCounts[cat] || 0;
          if (count === 0) return null;
          return (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-3 py-1.5 text-xs font-theme-data border rounded transition-colors ${
                selectedCategory === cat
                  ? `border-${meta.accent}/50 bg-${meta.accent}/10 text-${meta.accent}`
                  : 'border-border text-text-muted hover:border-[var(--accent)]/30'
              }`}
            >
              {meta.icon} {meta.label} ({count})
            </button>
          );
        })}
      </div>

      {/* Templates grid */}
      {selectedCategory === 'all' && grouped ? (
        // Grouped view
        <div className="space-y-8">
          {Object.entries(grouped).map(([category, templates]) => {
            const meta = CATEGORY_META[category as TemplateCategory];
            return (
              <div key={category}>
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-xs font-theme-data text-text-muted">{meta.icon}</span>
                  <h3 className="text-sm font-theme-data text-text">{meta.label}</h3>
                  <span className="text-xs text-text-muted">({templates.length})</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {templates.map((t) => (
                    <TemplateCard key={t.id} template={t} onSelect={onSelectTemplate} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        // Flat filtered view
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filteredTemplates.map((t) => (
            <TemplateCard key={t.id} template={t} onSelect={onSelectTemplate} />
          ))}
        </div>
      )}

      {filteredTemplates.length === 0 && (
        <div className="text-center py-12 text-text-muted text-sm font-theme-data">
          No templates match your search. Try different keywords.
        </div>
      )}
    </div>
  );
}
