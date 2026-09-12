'use client';

import { useState, useMemo } from 'react';
import type { MCPTool, ToolCategory } from '@/lib/mcp-tools-registry';
import { ToolCard } from './ToolCard';

interface ToolCatalogProps {
  tools: MCPTool[];
  categories: ToolCategory[];
}

export function ToolCatalog({ tools, categories }: ToolCatalogProps) {
  const [search, setSearch] = useState('');
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(
    () => new Set(categories.map((c) => c.name)),
  );
  const [expandedTool, setExpandedTool] = useState<string | null>(null);

  const filteredTools = useMemo(() => {
    return tools.filter((tool) => {
      if (!selectedCategories.has(tool.category)) return false;
      if (search) {
        const q = search.toLowerCase();
        return (
          tool.name.toLowerCase().includes(q) ||
          tool.description.toLowerCase().includes(q) ||
          tool.category.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [tools, selectedCategories, search]);

  const allSelected = selectedCategories.size === categories.length;

  const toggleCategory = (name: string) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        // Don't allow deselecting all
        if (next.size > 1) next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  const selectAll = () => {
    setSelectedCategories(new Set(categories.map((c) => c.name)));
  };

  return (
    <div className="space-y-6">
      {/* Search */}
      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search tools by name, description, or category..."
        className="w-full bg-[var(--surface)] border border-[var(--border)] rounded px-3 py-2 font-theme-data text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)] transition-colors"
      />

      {/* Category filter chips */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={selectAll}
          className={`px-3 py-1 text-xs font-theme-data border rounded transition-colors ${
            allSelected
              ? 'text-[var(--acid-green)] border-[var(--acid-green)] bg-[var(--acid-green)]/10'
              : 'text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/50'
          }`}
        >
          ALL ({tools.length})
        </button>
        {categories.map((cat) => {
          const active = selectedCategories.has(cat.name);
          return (
            <button
              key={cat.name}
              onClick={() => toggleCategory(cat.name)}
              className={`px-3 py-1 text-xs font-theme-data border rounded transition-colors ${
                active
                  ? 'text-[var(--acid-green)] border-[var(--acid-green)] bg-[var(--acid-green)]/10'
                  : 'text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/50'
              }`}
            >
              {cat.icon} {cat.name} ({cat.tools.length})
            </button>
          );
        })}
      </div>

      {/* Count */}
      <div className="text-xs font-theme-data text-[var(--text-muted)]">
        Showing {filteredTools.length} of {tools.length} tools
      </div>

      {/* Tool grid */}
      {filteredTools.length === 0 ? (
        <div className="py-12 text-center">
          <p className="text-sm font-theme-data text-[var(--text-muted)]">
            No tools match your search
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filteredTools.map((tool) => (
            <ToolCard
              key={tool.name}
              tool={tool}
              expanded={expandedTool === tool.name}
              onToggle={() => setExpandedTool((prev) => (prev === tool.name ? null : tool.name))}
            />
          ))}
        </div>
      )}
    </div>
  );
}
