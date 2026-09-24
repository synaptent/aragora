'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/lib/api';

interface Template {
  id: string;
  name: string;
  description: string;
  category: string;
  pattern?: string;
  steps_count: number;
  estimated_duration?: string;
  tags: string[];
}

interface Category {
  id: string;
  name: string;
  template_count: number;
}

interface Pattern {
  id: string;
  name: string;
  description: string;
  available: boolean;
}

export function WorkflowTemplatesBrowser() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [activeTab, setActiveTab] = useState<'templates' | 'patterns'>('templates');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [templatesRes, categoriesRes, patternsRes] = await Promise.all([
        apiFetch<{ templates: Template[] }>(
          `/api/workflow/templates${selectedCategory ? `?category=${selectedCategory}` : ''}`,
        ),
        apiFetch<{ categories: Category[] }>('/api/workflow/categories'),
        apiFetch<{ patterns: Pattern[] }>('/api/workflow/patterns'),
      ]);

      setTemplates(templatesRes.templates || []);
      setCategories(categoriesRes.categories || []);
      setPatterns(patternsRes.patterns || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch templates');
    } finally {
      setLoading(false);
    }
  }, [selectedCategory]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const filteredTemplates = templates.filter((template) => {
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (
      template.name.toLowerCase().includes(query) ||
      template.description.toLowerCase().includes(query) ||
      template.tags.some((tag) => tag.toLowerCase().includes(query))
    );
  });

  const handleRunTemplate = async (templateId: string) => {
    try {
      const response = await apiFetch<{ status: string }>(
        `/api/workflow/templates/${templateId}/run`,
        { method: 'POST', body: JSON.stringify({ inputs: {} }) },
      );
      alert(`Template execution started: ${response.status}`);
    } catch (err) {
      alert(`Failed to run template: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  if (loading) {
    return (
      <div className="card p-6">
        <div className="text-center text-text-muted font-theme-data">
          <span className="animate-pulse">Loading templates...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-6">
        <div className="text-center text-red-400 font-theme-data">
          <p>Error: {error}</p>
          <button
            onClick={fetchData}
            className="mt-4 px-4 py-2 border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10"
          >
            [RETRY]
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="font-theme-data text-[var(--accent)] text-xl">{'>'} WORKFLOW TEMPLATES</h2>
        <div className="text-xs font-theme-data text-text-muted">
          {templates.length} templates available
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-[var(--accent)]/20 pb-2">
        <button
          onClick={() => setActiveTab('templates')}
          className={`px-4 py-2 text-sm font-theme-data transition-colors ${
            activeTab === 'templates'
              ? 'border border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
              : 'border border-transparent text-text-muted hover:text-[var(--accent)]'
          }`}
        >
          [TEMPLATES]
        </button>
        <button
          onClick={() => setActiveTab('patterns')}
          className={`px-4 py-2 text-sm font-theme-data transition-colors ${
            activeTab === 'patterns'
              ? 'border border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
              : 'border border-transparent text-text-muted hover:text-[var(--accent)]'
          }`}
        >
          [PATTERNS]
        </button>
      </div>

      {activeTab === 'templates' && (
        <>
          {/* Filters */}
          <div className="flex flex-col md:flex-row gap-4">
            {/* Category Filter */}
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setSelectedCategory(null)}
                className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
                  !selectedCategory
                    ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                    : 'border-[var(--accent)]/30 text-text-muted hover:border-[var(--accent)]/60'
                }`}
              >
                [ALL]
              </button>
              {categories.map((category) => (
                <button
                  key={category.id}
                  onClick={() => setSelectedCategory(category.id)}
                  className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
                    selectedCategory === category.id
                      ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                      : 'border-[var(--accent)]/30 text-text-muted hover:border-[var(--accent)]/60'
                  }`}
                >
                  [{category.name.toUpperCase()}] ({category.template_count})
                </button>
              ))}
            </div>

            {/* Search */}
            <div className="flex-1 md:max-w-xs ml-auto">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search templates..."
                className="w-full px-4 py-2 text-sm font-theme-data bg-surface border border-[var(--accent)]/30
                         text-text placeholder-text-muted/50 focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
          </div>

          {/* Template Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredTemplates.map((template) => (
              <div
                key={template.id}
                className="card p-6 hover:border-[var(--accent)]/60 transition-colors cursor-pointer"
                onClick={() => setSelectedTemplate(template)}
              >
                {/* Category Badge */}
                <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-2">
                  [{template.category.toUpperCase()}]
                </div>

                {/* Name */}
                <h3 className="font-theme-data text-[var(--accent)] mb-2">{template.name}</h3>

                {/* Description */}
                <p className="text-sm font-theme-data text-text-muted mb-4 line-clamp-2">
                  {template.description}
                </p>

                {/* Tags */}
                <div className="flex flex-wrap gap-1 mb-4">
                  {template.tags.slice(0, 3).map((tag) => (
                    <span
                      key={tag}
                      className="px-2 py-0.5 text-xs font-theme-data bg-surface border border-[var(--accent)]/20 text-text-muted"
                    >
                      {tag}
                    </span>
                  ))}
                  {template.tags.length > 3 && (
                    <span className="px-2 py-0.5 text-xs font-theme-data text-text-muted">
                      +{template.tags.length - 3}
                    </span>
                  )}
                </div>

                {/* Meta */}
                <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
                  <span>{template.steps_count} steps</span>
                  {template.pattern && (
                    <span className="text-[var(--acid-cyan)]">{template.pattern}</span>
                  )}
                </div>
              </div>
            ))}
          </div>

          {filteredTemplates.length === 0 && (
            <div className="text-center py-12">
              <p className="text-text-muted font-theme-data">No templates match your search.</p>
            </div>
          )}
        </>
      )}

      {activeTab === 'patterns' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {patterns.map((pattern) => (
            <div
              key={pattern.id}
              className={`card p-6 ${
                pattern.available ? 'hover:border-[var(--accent)]/60' : 'opacity-50'
              } transition-colors`}
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-theme-data text-[var(--accent)]">{pattern.name}</h3>
                {pattern.available ? (
                  <span className="px-2 py-0.5 text-xs font-theme-data bg-green-400/20 text-green-400">
                    AVAILABLE
                  </span>
                ) : (
                  <span className="px-2 py-0.5 text-xs font-theme-data bg-red-400/20 text-red-400">
                    UNAVAILABLE
                  </span>
                )}
              </div>
              <p className="text-sm font-theme-data text-text-muted">{pattern.description}</p>
            </div>
          ))}
        </div>
      )}

      {/* Template Detail Modal */}
      {selectedTemplate && (
        <div className="fixed inset-0 z-[100] bg-bg/95 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="max-w-2xl w-full border border-[var(--accent)]/50 bg-surface p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-start mb-6">
              <div>
                <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-1">
                  [{selectedTemplate.category.toUpperCase()}]
                </div>
                <h2 className="text-xl font-theme-data text-[var(--accent)]">
                  {selectedTemplate.name}
                </h2>
              </div>
              <button
                onClick={() => setSelectedTemplate(null)}
                className="text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [X]
              </button>
            </div>

            <p className="font-theme-data text-sm text-text-muted mb-6">
              {selectedTemplate.description}
            </p>

            {/* Configuration Summary */}
            <div className="p-4 bg-bg border border-[var(--accent)]/20 mb-6">
              <div className="grid grid-cols-2 gap-4 text-sm font-theme-data">
                <div>
                  <span className="text-text-muted">Steps:</span>{' '}
                  <span className="text-[var(--acid-cyan)]">{selectedTemplate.steps_count}</span>
                </div>
                {selectedTemplate.pattern && (
                  <div>
                    <span className="text-text-muted">Pattern:</span>{' '}
                    <span className="text-[var(--acid-cyan)]">{selectedTemplate.pattern}</span>
                  </div>
                )}
                {selectedTemplate.estimated_duration && (
                  <div>
                    <span className="text-text-muted">Est. Duration:</span>{' '}
                    <span className="text-[var(--acid-cyan)]">
                      {selectedTemplate.estimated_duration}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Tags */}
            <div className="flex flex-wrap gap-2 mb-6">
              {selectedTemplate.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-3 py-1 text-xs font-theme-data bg-surface border border-[var(--accent)]/20 text-text-muted"
                >
                  {tag}
                </span>
              ))}
            </div>

            {/* Actions */}
            <div className="flex gap-3">
              <button
                onClick={() => setSelectedTemplate(null)}
                className="px-4 py-2 font-theme-data text-sm border border-[var(--accent)]/30
                         text-text-muted hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
              >
                [CANCEL]
              </button>
              <button
                onClick={() => handleRunTemplate(selectedTemplate.id)}
                className="flex-1 px-6 py-2 font-theme-data text-sm bg-[var(--accent)] text-bg
                         hover:bg-[var(--accent)]/80 transition-colors"
              >
                [RUN TEMPLATE]
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default WorkflowTemplatesBrowser;
