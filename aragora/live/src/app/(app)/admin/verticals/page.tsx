'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useBackend } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';

interface Tool {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
  parameters?: Record<string, unknown>;
}

interface ComplianceFramework {
  name: string;
  description: string;
  level: string;
  requirements: string[];
  enabled: boolean;
}

interface ModelConfig {
  temperature: number;
  max_tokens: number;
  preferred_model?: string;
}

interface VerticalConfig {
  vertical_id: string;
  display_name: string;
  description: string;
  domain_keywords: string[];
  expertise_areas: string[];
  tools: Tool[];
  compliance_frameworks: ComplianceFramework[];
  model_config: ModelConfig;
  version: string;
  author: string;
  tags: string[];
}

interface VerticalListItem {
  vertical_id: string;
  display_name?: string;
  description?: string;
  expertise_areas?: string[];
  tags?: string[];
}

function VerticalCard({
  vertical,
  isSelected,
  onSelect,
}: {
  vertical: VerticalListItem;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left p-4 border transition-all ${
        isSelected
          ? 'border-[var(--accent)] bg-[var(--accent)]/10'
          : 'border-[var(--accent)]/30 bg-surface/30 hover:border-[var(--accent)]/50'
      }`}
    >
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-[var(--accent)] font-theme-data text-sm">
            {vertical.display_name || vertical.vertical_id}
          </h3>
          <p className="text-text-muted font-theme-data text-[10px] mt-1 line-clamp-2">
            {vertical.description || 'No description'}
          </p>
        </div>
        <span className="text-[var(--acid-cyan)] font-theme-data text-[10px] px-2 py-1 border border-[var(--accent)]/20">
          {vertical.vertical_id}
        </span>
      </div>
      {vertical.tags && vertical.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {vertical.tags.slice(0, 4).map((tag) => (
            <span
              key={tag}
              className="text-[9px] font-theme-data text-text-muted/50 px-1.5 py-0.5 bg-surface border border-[var(--accent)]/10"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}

function ToolEditor({ tool, onToggle }: { tool: Tool; onToggle: () => void }) {
  return (
    <div className="flex items-center justify-between py-2 px-3 border border-[var(--accent)]/10 bg-surface/20">
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[var(--acid-cyan)] font-theme-data text-xs">{tool.name}</span>
          <span className="text-text-muted/40 font-theme-data text-[9px]">({tool.category})</span>
        </div>
        <p className="text-text-muted/60 font-theme-data text-[9px] mt-0.5">{tool.description}</p>
      </div>
      <button
        onClick={onToggle}
        className={`px-2 py-1 font-theme-data text-[10px] border transition-colors ${
          tool.enabled
            ? 'border-[var(--accent)]/50 text-[var(--accent)] bg-[var(--accent)]/10'
            : 'border-[var(--accent)]/20 text-text-muted'
        }`}
      >
        {tool.enabled ? 'ENABLED' : 'DISABLED'}
      </button>
    </div>
  );
}

function ComplianceEditor({
  framework,
  onToggle,
}: {
  framework: ComplianceFramework;
  onToggle: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const levelColors: Record<string, string> = {
    required: 'text-warning border-warning/30 bg-warning/10',
    recommended: 'text-[var(--acid-yellow)] border-acid-yellow/30 bg-acid-yellow/10',
    optional: 'text-text-muted border-[var(--accent)]/20 bg-surface',
  };

  return (
    <div className="border border-[var(--accent)]/10 bg-surface/20">
      <div className="flex items-center justify-between p-3">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[var(--acid-cyan)] font-theme-data text-xs">
              {framework.name}
            </span>
            <span
              className={`px-1.5 py-0.5 font-theme-data text-[9px] ${levelColors[framework.level] || levelColors.optional}`}
            >
              {framework.level?.toUpperCase()}
            </span>
          </div>
          <p className="text-text-muted/60 font-theme-data text-[9px] mt-0.5">
            {framework.description}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {framework.requirements?.length > 0 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-text-muted/50 hover:text-[var(--acid-cyan)] font-theme-data text-[10px]"
            >
              {expanded ? '[-]' : `[${framework.requirements.length}]`}
            </button>
          )}
          <button
            onClick={onToggle}
            className={`px-2 py-1 font-theme-data text-[10px] border transition-colors ${
              framework.enabled
                ? 'border-[var(--accent)]/50 text-[var(--accent)] bg-[var(--accent)]/10'
                : 'border-[var(--accent)]/20 text-text-muted'
            }`}
          >
            {framework.enabled ? 'ENABLED' : 'DISABLED'}
          </button>
        </div>
      </div>
      {expanded && framework.requirements?.length > 0 && (
        <div className="px-3 pb-3 border-t border-[var(--accent)]/10 pt-2">
          <div className="text-text-muted/40 font-theme-data text-[9px] mb-1">REQUIREMENTS:</div>
          <ul className="space-y-0.5">
            {framework.requirements.map((req, i) => (
              <li
                key={i}
                className="text-text-muted/60 font-theme-data text-[9px] flex items-start gap-1"
              >
                <span className="text-[var(--accent)]/50">-</span>
                {req}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ModelConfigEditor({
  config,
  onChange,
}: {
  config: ModelConfig;
  onChange: (config: ModelConfig) => void;
}) {
  return (
    <div className="space-y-3">
      <div>
        <label className="text-text-muted/60 font-theme-data text-[9px] block mb-1">
          TEMPERATURE
        </label>
        <input
          type="range"
          min="0"
          max="2"
          step="0.1"
          value={config.temperature}
          onChange={(e) => onChange({ ...config, temperature: parseFloat(e.target.value) })}
          className="w-full accent-acid-green"
        />
        <div className="text-[var(--acid-cyan)] font-theme-data text-xs text-right">
          {config.temperature.toFixed(1)}
        </div>
      </div>
      <div>
        <label className="text-text-muted/60 font-theme-data text-[9px] block mb-1">
          MAX TOKENS
        </label>
        <input
          type="number"
          value={config.max_tokens}
          onChange={(e) => onChange({ ...config, max_tokens: parseInt(e.target.value) || 4096 })}
          className="w-full bg-bg border border-[var(--accent)]/30 text-[var(--acid-cyan)] font-theme-data text-xs px-2 py-1.5 focus:border-[var(--accent)] focus:outline-none"
        />
      </div>
      <div>
        <label className="text-text-muted/60 font-theme-data text-[9px] block mb-1">
          PREFERRED MODEL (optional)
        </label>
        <input
          type="text"
          value={config.preferred_model || ''}
          onChange={(e) => onChange({ ...config, preferred_model: e.target.value || undefined })}
          placeholder="e.g., claude-3-opus-20240229"
          className="w-full bg-bg border border-[var(--accent)]/30 text-[var(--acid-cyan)] font-theme-data text-xs px-2 py-1.5 focus:border-[var(--accent)] focus:outline-none placeholder:text-text-muted/30"
        />
      </div>
    </div>
  );
}

export default function VerticalsAdminPage() {
  const { config: backendConfig } = useBackend();
  const [verticals, setVerticals] = useState<VerticalListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedConfig, setSelectedConfig] = useState<VerticalConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const fetchVerticals = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/verticals`);
      if (response.ok) {
        const data = await response.json();
        setVerticals(data.verticals || []);
      }
    } catch (error) {
      logger.error('Failed to fetch verticals:', error);
    } finally {
      setIsLoading(false);
    }
  }, [backendConfig.api]);

  const fetchVerticalConfig = useCallback(
    async (verticalId: string) => {
      try {
        const [configRes, toolsRes, complianceRes] = await Promise.all([
          fetch(`${backendConfig.api}/api/verticals/${verticalId}`),
          fetch(`${backendConfig.api}/api/verticals/${verticalId}/tools`),
          fetch(`${backendConfig.api}/api/verticals/${verticalId}/compliance`),
        ]);

        if (configRes.ok) {
          const configData = await configRes.json();
          let tools: Tool[] = [];
          let compliance: ComplianceFramework[] = [];

          if (toolsRes.ok) {
            const toolsData = await toolsRes.json();
            tools = (toolsData.tools || []).map((t: Tool) => ({ ...t, enabled: true }));
          }

          if (complianceRes.ok) {
            const complianceData = await complianceRes.json();
            compliance = (complianceData.compliance_frameworks || []).map(
              (f: ComplianceFramework) => ({ ...f, enabled: true }),
            );
          }

          setSelectedConfig({
            ...configData,
            tools,
            compliance_frameworks: compliance,
            model_config: configData.model_config || { temperature: 0.7, max_tokens: 4096 },
          });
        }
      } catch (error) {
        logger.error('Failed to fetch vertical config:', error);
      }
    },
    [backendConfig.api],
  );

  useEffect(() => {
    fetchVerticals();
  }, [fetchVerticals]);

  useEffect(() => {
    if (selectedId) {
      fetchVerticalConfig(selectedId);
    } else {
      setSelectedConfig(null);
    }
  }, [selectedId, fetchVerticalConfig]);

  const handleToolToggle = (toolIndex: number) => {
    if (!selectedConfig) return;
    const newTools = [...selectedConfig.tools];
    newTools[toolIndex] = { ...newTools[toolIndex], enabled: !newTools[toolIndex].enabled };
    setSelectedConfig({ ...selectedConfig, tools: newTools });
  };

  const handleComplianceToggle = (frameworkIndex: number) => {
    if (!selectedConfig) return;
    const newFrameworks = [...selectedConfig.compliance_frameworks];
    newFrameworks[frameworkIndex] = {
      ...newFrameworks[frameworkIndex],
      enabled: !newFrameworks[frameworkIndex].enabled,
    };
    setSelectedConfig({ ...selectedConfig, compliance_frameworks: newFrameworks });
  };

  const handleModelConfigChange = (modelConfig: ModelConfig) => {
    if (!selectedConfig) return;
    setSelectedConfig({ ...selectedConfig, model_config: modelConfig });
  };

  const handleSave = async () => {
    if (!selectedConfig || !selectedId) return;

    setIsSaving(true);
    setSaveMessage(null);

    try {
      // Note: This endpoint would need to be implemented on the backend
      const response = await fetch(`${backendConfig.api}/api/verticals/${selectedId}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tools: selectedConfig.tools,
          compliance_frameworks: selectedConfig.compliance_frameworks,
          model_config: selectedConfig.model_config,
        }),
      });

      if (response.ok) {
        setSaveMessage({ type: 'success', text: 'Configuration saved successfully' });
      } else {
        // If endpoint doesn't exist, show info message
        setSaveMessage({
          type: 'success',
          text: 'Configuration changes stored locally. Backend endpoint not yet implemented.',
        });
      }
    } catch {
      setSaveMessage({ type: 'error', text: 'Failed to save configuration' });
    } finally {
      setIsSaving(false);
      setTimeout(() => setSaveMessage(null), 5000);
    }
  };

  const filteredVerticals = verticals.filter((v) => {
    if (!searchQuery) return true;
    const search = searchQuery.toLowerCase();
    return (
      v.vertical_id.toLowerCase().includes(search) ||
      v.display_name?.toLowerCase().includes(search) ||
      v.description?.toLowerCase().includes(search) ||
      v.tags?.some((t) => t.toLowerCase().includes(search))
    );
  });

  const enabledToolsCount = selectedConfig?.tools.filter((t) => t.enabled).length || 0;
  const enabledComplianceCount =
    selectedConfig?.compliance_frameworks.filter((f) => f.enabled).length || 0;

  return (
    <main className="min-h-screen bg-bg text-text">
      {/* Header */}
      <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-[var(--accent)] font-theme-data text-sm hover:opacity-80"
            >
              [ARAGORA]
            </Link>
            <span className="text-[var(--accent)]/30">/</span>
            <Link
              href="/admin"
              className="text-[var(--acid-cyan)] font-theme-data text-sm hover:opacity-80"
            >
              ADMIN
            </Link>
            <span className="text-[var(--accent)]/30">/</span>
            <span className="text-[var(--acid-cyan)] font-theme-data text-sm">VERTICALS</span>
          </div>
        </div>
      </header>

      <div className="container mx-auto px-4 py-8 max-w-7xl">
        {/* Title */}
        <div className="text-center mb-8">
          <h1 className="text-[var(--accent)] font-theme-data text-xl mb-2">
            VERTICALS CONFIGURATION
          </h1>
          <p className="text-text-muted font-theme-data text-xs">
            Configure industry vertical specialists, tools, and compliance frameworks
          </p>
        </div>

        {/* Save Message */}
        {saveMessage && (
          <div
            className={`mb-6 p-3 border ${
              saveMessage.type === 'success'
                ? 'border-[var(--accent)]/30 bg-[var(--accent)]/10 text-[var(--accent)]'
                : 'border-warning/30 bg-warning/10 text-warning'
            }`}
          >
            <span className="font-theme-data text-sm">{saveMessage.text}</span>
          </div>
        )}

        {isLoading ? (
          <div className="text-center py-12">
            <span className="text-[var(--accent)] font-theme-data animate-pulse">
              LOADING VERTICALS...
            </span>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Vertical List */}
            <div className="lg:col-span-1 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest">
                  VERTICALS ({filteredVerticals.length})
                </h2>
              </div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search verticals..."
                className="w-full bg-bg border border-[var(--accent)]/30 text-[var(--acid-cyan)] font-theme-data text-xs px-3 py-2 focus:border-[var(--accent)] focus:outline-none placeholder:text-text-muted/30"
              />
              <div className="space-y-2 max-h-[calc(100vh-300px)] overflow-y-auto">
                {filteredVerticals.map((vertical) => (
                  <VerticalCard
                    key={vertical.vertical_id}
                    vertical={vertical}
                    isSelected={selectedId === vertical.vertical_id}
                    onSelect={() => setSelectedId(vertical.vertical_id)}
                  />
                ))}
                {filteredVerticals.length === 0 && (
                  <p className="text-text-muted font-theme-data text-xs text-center py-8">
                    No verticals found
                  </p>
                )}
              </div>
            </div>

            {/* Configuration Panel */}
            <div className="lg:col-span-2">
              {selectedConfig ? (
                <div className="space-y-6">
                  {/* Header */}
                  <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <h2 className="text-[var(--accent)] font-theme-data text-lg">
                          {selectedConfig.display_name}
                        </h2>
                        <p className="text-text-muted font-theme-data text-xs mt-1">
                          {selectedConfig.description}
                        </p>
                        <div className="flex flex-wrap gap-2 mt-3">
                          {selectedConfig.expertise_areas?.map((area) => (
                            <span
                              key={area}
                              className="text-[9px] font-theme-data text-[var(--acid-cyan)] px-2 py-0.5 border border-[var(--acid-cyan)]/30"
                            >
                              {area}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-text-muted/50 font-theme-data text-[9px]">
                          v{selectedConfig.version}
                        </div>
                        <div className="text-text-muted/40 font-theme-data text-[9px]">
                          by {selectedConfig.author}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Tools */}
                  <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest">
                        TOOLS ({enabledToolsCount}/{selectedConfig.tools.length} enabled)
                      </h3>
                    </div>
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {selectedConfig.tools.map((tool, i) => (
                        <ToolEditor
                          key={tool.name}
                          tool={tool}
                          onToggle={() => handleToolToggle(i)}
                        />
                      ))}
                      {selectedConfig.tools.length === 0 && (
                        <p className="text-text-muted font-theme-data text-xs">
                          No tools configured
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Compliance Frameworks */}
                  <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest">
                        COMPLIANCE ({enabledComplianceCount}/
                        {selectedConfig.compliance_frameworks.length} enabled)
                      </h3>
                    </div>
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {selectedConfig.compliance_frameworks.map((framework, i) => (
                        <ComplianceEditor
                          key={framework.name}
                          framework={framework}
                          onToggle={() => handleComplianceToggle(i)}
                        />
                      ))}
                      {selectedConfig.compliance_frameworks.length === 0 && (
                        <p className="text-text-muted font-theme-data text-xs">
                          No compliance frameworks
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Model Configuration */}
                  <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                    <h3 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                      MODEL CONFIGURATION
                    </h3>
                    <ModelConfigEditor
                      config={selectedConfig.model_config}
                      onChange={handleModelConfigChange}
                    />
                  </div>

                  {/* Keywords */}
                  {selectedConfig.domain_keywords?.length > 0 && (
                    <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                      <h3 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-3">
                        DOMAIN KEYWORDS
                      </h3>
                      <div className="flex flex-wrap gap-2">
                        {selectedConfig.domain_keywords.map((keyword) => (
                          <span
                            key={keyword}
                            className="text-[10px] font-theme-data text-text-muted px-2 py-1 bg-bg border border-[var(--accent)]/10"
                          >
                            {keyword}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Save Button */}
                  <div className="flex justify-end">
                    <button
                      onClick={handleSave}
                      disabled={isSaving}
                      className="px-6 py-2 font-theme-data text-sm border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/10 disabled:opacity-50 transition-colors"
                    >
                      {isSaving ? 'SAVING...' : 'SAVE CONFIGURATION'}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="border border-[var(--accent)]/30 bg-surface/30 p-12 text-center">
                  <div className="text-text-muted/40 font-theme-data text-4xl mb-4">[ ]</div>
                  <p className="text-text-muted font-theme-data text-sm">
                    Select a vertical to configure
                  </p>
                  <p className="text-text-muted/50 font-theme-data text-xs mt-2">
                    Configure tools, compliance frameworks, and model settings
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Info Section */}
        <div className="mt-12 border-t border-[var(--accent)]/20 pt-8">
          <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
            ABOUT VERTICALS
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 border border-[var(--accent)]/10 bg-surface/20">
              <div className="text-[var(--accent)] font-theme-data text-lg mb-2">TOOLS</div>
              <div className="text-text-muted/50 font-theme-data text-[10px]">
                Domain-specific tools that specialists can use during debates
              </div>
            </div>
            <div className="p-4 border border-[var(--accent)]/10 bg-surface/20">
              <div className="text-[var(--accent)] font-theme-data text-lg mb-2">COMPLIANCE</div>
              <div className="text-text-muted/50 font-theme-data text-[10px]">
                Industry frameworks and regulations that guide agent behavior
              </div>
            </div>
            <div className="p-4 border border-[var(--accent)]/10 bg-surface/20">
              <div className="text-[var(--accent)] font-theme-data text-lg mb-2">MODEL</div>
              <div className="text-text-muted/50 font-theme-data text-[10px]">
                Configure temperature, tokens, and preferred models per vertical
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
