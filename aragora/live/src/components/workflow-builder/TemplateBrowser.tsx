'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import type { WorkflowTemplate } from './types';

interface TemplateBrowserProps {
  onSelect: (template: WorkflowTemplate) => void;
  onClose: () => void;
}

const categoryIcons: Record<string, string> = {
  legal: '⚖️',
  healthcare: '🏥',
  code: '💻',
  accounting: '📊',
};

const categoryColors: Record<string, string> = {
  legal: 'bg-purple-500/20 border-purple-500 text-purple-300',
  healthcare: 'bg-green-500/20 border-green-500 text-green-300',
  code: 'bg-blue-500/20 border-blue-500 text-blue-300',
  accounting: 'bg-yellow-500/20 border-yellow-500 text-yellow-300',
};

export function TemplateBrowser({ onSelect, onClose }: TemplateBrowserProps) {
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTemplates = useCallback(async () => {
    try {
      setLoading(true);
      const url = new URL(`${API_BASE_URL}/api/workflow-templates`);
      if (selectedCategory) {
        url.searchParams.set('category', selectedCategory);
      }

      const response = await fetch(url.toString());
      if (!response.ok) throw new Error('Failed to fetch templates');

      const data = await response.json();
      setTemplates(data.templates || []);
      setCategories(data.categories || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load templates');
    } finally {
      setLoading(false);
    }
  }, [selectedCategory]);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const handleSelectTemplate = async (templateId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/workflow-templates/${templateId}`);
      if (!response.ok) throw new Error('Failed to fetch template');

      const data = await response.json();
      onSelect(data.template);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load template');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm">
      <div className="w-full max-w-4xl max-h-[80vh] bg-surface border border-border rounded-lg shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div>
            <h2 className="text-lg font-theme-data font-bold text-text">Workflow Templates</h2>
            <p className="text-sm text-text-muted">
              Choose a pre-built workflow to get started quickly
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-text-muted hover:text-text transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Category tabs */}
        <div className="flex gap-2 p-4 border-b border-border overflow-x-auto">
          <button
            onClick={() => setSelectedCategory(null)}
            className={`px-4 py-2 rounded font-theme-data text-sm transition-colors ${
              selectedCategory === null
                ? 'bg-[var(--accent)] text-bg'
                : 'bg-bg text-text-muted hover:text-text'
            }`}
          >
            All
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-4 py-2 rounded font-theme-data text-sm transition-colors flex items-center gap-2 ${
                selectedCategory === cat
                  ? 'bg-[var(--accent)] text-bg'
                  : 'bg-bg text-text-muted hover:text-text'
              }`}
            >
              <span>{categoryIcons[cat] || '📁'}</span>
              <span className="capitalize">{cat}</span>
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="p-4 overflow-y-auto max-h-[50vh]">
          {loading && (
            <div className="flex items-center justify-center py-8">
              <div className="animate-pulse text-text-muted">Loading templates...</div>
            </div>
          )}

          {error && (
            <div className="p-4 bg-red-500/20 border border-red-500/50 rounded text-red-400 text-sm">
              {error}
            </div>
          )}

          {!loading && !error && templates.length === 0 && (
            <div className="text-center py-8 text-text-muted">No templates found</div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {templates.map((template) => (
              <button
                key={template.id}
                onClick={() => handleSelectTemplate(template.id)}
                className={`
                  p-4 rounded-lg border-2 text-left transition-all
                  hover:scale-[1.02] hover:shadow-lg
                  ${categoryColors[template.category] || 'bg-surface border-border'}
                `}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-lg">{categoryIcons[template.category] || '📁'}</span>
                  <h3 className="font-theme-data font-bold text-text">{template.name}</h3>
                </div>

                <p className="text-sm text-text-muted mb-3 line-clamp-2">{template.description}</p>

                <div className="flex flex-wrap gap-1">
                  {template.tags.slice(0, 4).map((tag) => (
                    <span
                      key={tag}
                      className="px-2 py-0.5 text-xs bg-bg/50 rounded font-theme-data"
                    >
                      {tag}
                    </span>
                  ))}
                </div>

                <div className="mt-3 text-xs text-text-muted font-theme-data">
                  {template.steps?.length || 0} steps | v{template.version}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-border bg-bg/50">
          <p className="text-xs text-text-muted font-theme-data">
            {templates.length} template{templates.length !== 1 ? 's' : ''} available
          </p>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-surface border border-border text-text font-theme-data text-sm hover:border-text transition-colors rounded"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export default TemplateBrowser;
