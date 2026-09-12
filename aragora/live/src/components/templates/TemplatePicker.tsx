'use client';

import { useState } from 'react';
import Link from 'next/link';
import {
  TEMPLATES,
  CATEGORY_META,
  CATEGORY_ORDER,
  groupByCategory,
  type TemplateCategory,
  type TemplateData,
} from './templateData';

interface TemplatePickerProps {
  /** Show compact mode for landing page (fewer details, no search) */
  compact?: boolean;
  /** Maximum templates to show per category in compact mode */
  compactLimit?: number;
}

function TemplateCard({ template, compact }: { template: TemplateData; compact?: boolean }) {
  const meta = CATEGORY_META[template.category];

  return (
    <Link
      href={`/arena?template=${encodeURIComponent(template.id)}`}
      className={`block border border-${meta.accent}/20 bg-surface/30 p-4
                  hover:border-${meta.accent}/50 hover:bg-surface/50 transition-all group`}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-${meta.accent}/60 font-theme-data text-xs`}>[{meta.label}]</span>
      </div>
      <h3
        className={`text-${meta.accent} font-theme-data text-sm mb-1 group-hover:text-${meta.accent}/80`}
      >
        {template.name}
      </h3>
      <p className="text-text-muted text-xs font-theme-data leading-relaxed mb-3">
        {template.description}
      </p>

      {!compact && template.exampleTopics.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {template.exampleTopics.slice(0, 2).map((topic) => (
            <span
              key={topic}
              className={`px-2 py-0.5 text-[10px] font-theme-data bg-${meta.accent}/5 text-${meta.accent}/70 border border-${meta.accent}/10`}
            >
              {topic.length > 50 ? topic.slice(0, 47) + '...' : topic}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between text-[10px] font-theme-data text-text-muted/50">
        <span>{template.agents.length} agents</span>
        <span>{template.rounds} rounds</span>
      </div>
    </Link>
  );
}

export function TemplatePicker({ compact = false, compactLimit = 2 }: TemplatePickerProps) {
  const [selectedCategory, setSelectedCategory] = useState<TemplateCategory | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const grouped = groupByCategory();

  // Filter templates
  const filteredTemplates = TEMPLATES.filter((t) => {
    const matchesCategory = !selectedCategory || t.category === selectedCategory;
    const matchesSearch =
      !searchQuery ||
      t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.tags.some((tag) => tag.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchesCategory && matchesSearch;
  });

  // In compact mode, show grouped view
  if (compact) {
    return (
      <section className="py-8 border-t border-[var(--accent)]/20">
        <div className="container mx-auto px-4">
          <div className="text-center mb-6">
            <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-2">
              TEMPLATES
            </h2>
            <p className="text-text-muted font-theme-data text-xs max-w-xl mx-auto">
              25 pre-built deliberation templates across 8 verticals
            </p>
          </div>

          {/* Category chips for quick filtering */}
          <div className="flex flex-wrap justify-center gap-2 mb-6">
            {CATEGORY_ORDER.map((cat) => {
              const meta = CATEGORY_META[cat];
              const count = grouped.get(cat)?.length ?? 0;
              if (count === 0) return null;
              return (
                <button
                  key={cat}
                  onClick={() => setSelectedCategory(selectedCategory === cat ? null : cat)}
                  className={`px-2 py-1 text-[10px] font-theme-data border transition-colors
                    ${
                      selectedCategory === cat
                        ? `border-${meta.accent} bg-${meta.accent}/10 text-${meta.accent}`
                        : `border-[var(--accent)]/20 text-text-muted/50 hover:text-${meta.accent} hover:border-${meta.accent}/40`
                    }`}
                >
                  <span className="mr-1">{meta.icon}</span>
                  {meta.label}
                  <span className="ml-1 opacity-50">({count})</span>
                </button>
              );
            })}
          </div>

          {/* Template grid -- show limited per category or filtered */}
          {selectedCategory ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 max-w-5xl mx-auto">
              {filteredTemplates.map((t) => (
                <TemplateCard key={t.id} template={t} compact />
              ))}
            </div>
          ) : (
            <div className="space-y-4 max-w-5xl mx-auto">
              {CATEGORY_ORDER.map((cat) => {
                const items = grouped.get(cat);
                if (!items) return null;
                const meta = CATEGORY_META[cat];
                return (
                  <div key={cat}>
                    <h3
                      className={`text-${meta.accent} font-theme-data text-xs mb-2 flex items-center gap-2`}
                    >
                      <span className="opacity-60">{meta.icon}</span>
                      {meta.label}
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                      {items.slice(0, compactLimit).map((t) => (
                        <TemplateCard key={t.id} template={t} compact />
                      ))}
                      {items.length > compactLimit && (
                        <Link
                          href="/templates"
                          className={`flex items-center justify-center border border-${meta.accent}/10
                                      text-${meta.accent}/40 font-theme-data text-xs p-4
                                      hover:border-${meta.accent}/30 hover:text-${meta.accent}/60 transition-colors`}
                        >
                          +{items.length - compactLimit} more
                        </Link>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="text-center mt-6">
            <Link
              href="/templates"
              className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              [VIEW ALL 25 TEMPLATES]
            </Link>
          </div>
        </div>
      </section>
    );
  }

  // Full mode: used on /templates page
  return (
    <div>
      {/* Filters */}
      <div className="flex flex-col md:flex-row gap-4 mb-8">
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setSelectedCategory(null)}
            className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
              !selectedCategory
                ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                : 'border-[var(--accent)]/30 text-text-muted hover:border-[var(--accent)]/60'
            }`}
          >
            [ALL] ({TEMPLATES.length})
          </button>
          {CATEGORY_ORDER.map((cat) => {
            const meta = CATEGORY_META[cat];
            const count = grouped.get(cat)?.length ?? 0;
            if (count === 0) return null;
            return (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
                  selectedCategory === cat
                    ? `border-${meta.accent} bg-${meta.accent}/20 text-${meta.accent}`
                    : `border-[var(--accent)]/30 text-text-muted hover:border-${meta.accent}/60`
                }`}
              >
                [{meta.label}] ({count})
              </button>
            );
          })}
        </div>

        <div className="flex-1 md:max-w-xs ml-auto">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Filter templates..."
            className="w-full px-4 py-2 text-sm font-theme-data bg-surface border border-[var(--accent)]/30
                     text-text placeholder-text-muted/50 focus:border-[var(--accent)] focus:outline-none"
          />
        </div>
      </div>

      {/* Template Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredTemplates.map((template) => (
          <TemplateCard key={template.id} template={template} />
        ))}
      </div>

      {filteredTemplates.length === 0 && (
        <div className="text-center py-12">
          <p className="text-text-muted font-theme-data">No templates match your search.</p>
        </div>
      )}
    </div>
  );
}
