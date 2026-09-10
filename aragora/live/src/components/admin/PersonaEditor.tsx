'use client';

import { useState, useEffect, useCallback } from 'react';

interface Persona {
  agent_name: string;
  description: string;
  traits: string[];
  expertise: Record<string, number>;
  created_at: string;
  updated_at: string;
}

interface PersonaOptions {
  traits: string[];
  expertise_domains: string[];
}

interface PersonaEditorProps {
  apiBase?: string;
}

type ViewMode = 'grid' | 'list';

export function PersonaEditor({ apiBase = '/api' }: PersonaEditorProps) {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [options, setOptions] = useState<PersonaOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPersona, setSelectedPersona] = useState<Persona | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [editingPersona, setEditingPersona] = useState<Persona | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchPersonas = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [personasRes, optionsRes] = await Promise.all([
        fetch(`${apiBase}/personas`),
        fetch(`${apiBase}/personas/options`),
      ]);

      if (!personasRes.ok) {
        throw new Error(`Failed to fetch personas: ${personasRes.status}`);
      }

      const personasData = await personasRes.json();
      // Convert expertise from list to object if needed
      const normalizedPersonas = (personasData.personas || []).map((p: Persona) => ({
        ...p,
        expertise: Array.isArray(p.expertise)
          ? Object.fromEntries(p.expertise.map((e: string) => [e, 0.5]))
          : p.expertise || {},
      }));
      setPersonas(normalizedPersonas);

      if (optionsRes.ok) {
        const optionsData = await optionsRes.json();
        setOptions(optionsData);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load personas');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchPersonas();
  }, [fetchPersonas]);

  const filteredPersonas = personas.filter((persona) => {
    const query = searchQuery.toLowerCase();
    const expertiseKeys = Object.keys(persona.expertise || {});
    return (
      persona.agent_name.toLowerCase().includes(query) ||
      persona.description.toLowerCase().includes(query) ||
      persona.traits.some((t) => t.toLowerCase().includes(query)) ||
      expertiseKeys.some((e) => e.toLowerCase().includes(query))
    );
  });

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  const handleCreate = () => {
    setEditingPersona({
      agent_name: '',
      description: '',
      traits: [],
      expertise: {},
      created_at: '',
      updated_at: '',
    });
    setIsCreating(true);
  };

  const handleEdit = (persona: Persona) => {
    setEditingPersona({ ...persona });
    setIsCreating(false);
  };

  const handleSave = async () => {
    if (!editingPersona) return;

    setSaving(true);
    try {
      const isNew = isCreating;
      const url = isNew
        ? `${apiBase}/personas`
        : `${apiBase}/agent/${editingPersona.agent_name}/persona`;
      const method = isNew ? 'POST' : 'PUT';

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_name: editingPersona.agent_name,
          description: editingPersona.description,
          traits: editingPersona.traits,
          expertise: editingPersona.expertise,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to save persona');
      }

      await fetchPersonas();
      setEditingPersona(null);
      setIsCreating(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save persona');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (agentName: string) => {
    if (!confirm(`Delete persona for ${agentName}? This cannot be undone.`)) {
      return;
    }

    try {
      const response = await fetch(`${apiBase}/agent/${agentName}/persona`, { method: 'DELETE' });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to delete persona');
      }

      await fetchPersonas();
      setSelectedPersona(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete persona');
    }
  };

  if (loading) {
    return (
      <div className="bg-surface border border-[var(--accent)]/30 p-8">
        <div className="flex items-center justify-center gap-2">
          <div className="w-2 h-2 bg-[var(--accent)] rounded-full animate-pulse" />
          <span className="text-xs font-theme-data text-[var(--accent)]">LOADING PERSONAS...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-surface border border-[var(--crimson)]/30 p-4">
        <div className="flex items-center gap-2">
          <span className="text-[var(--crimson)] text-xs font-theme-data">ERROR:</span>
          <span className="text-text-primary text-xs font-theme-data">{error}</span>
        </div>
        <button
          onClick={() => {
            setError(null);
            fetchPersonas();
          }}
          className="mt-3 px-3 py-1.5 text-xs font-theme-data bg-[var(--crimson)]/20 text-[var(--crimson)] border border-[var(--crimson)]/40 hover:bg-[var(--crimson)]/30 transition-colors"
        >
          RETRY
        </button>
      </div>
    );
  }

  return (
    <div className="bg-surface border border-[var(--accent)]/30">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
            {'>'} PERSONA MANAGER
          </span>
          <span className="text-xs font-theme-data text-text-muted">
            {personas.length} agent{personas.length !== 1 ? 's' : ''}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCreate}
            className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40 hover:bg-[var(--accent)]/30 transition-colors"
          >
            + NEW
          </button>
          <button
            onClick={() => setViewMode('grid')}
            className={`px-2 py-1 text-xs font-theme-data border ${
              viewMode === 'grid'
                ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40'
                : 'text-text-muted border-border hover:border-[var(--accent)]/40'
            }`}
          >
            GRID
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`px-2 py-1 text-xs font-theme-data border ${
              viewMode === 'list'
                ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40'
                : 'text-text-muted border-border hover:border-[var(--accent)]/40'
            }`}
          >
            LIST
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="px-4 py-3 border-b border-[var(--accent)]/10">
        <input
          type="text"
          placeholder="Search personas by name, traits, or expertise..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full bg-bg border border-border px-3 py-2 text-xs font-theme-data text-text-primary placeholder-text-muted focus:border-[var(--accent)]/50 focus:outline-none"
        />
      </div>

      {/* Content */}
      <div className="p-4">
        {filteredPersonas.length === 0 ? (
          <div className="text-center py-8">
            <span className="text-xs font-theme-data text-text-muted">
              {searchQuery ? 'No personas match your search' : 'No personas configured'}
            </span>
          </div>
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredPersonas.map((persona) => (
              <PersonaCard
                key={persona.agent_name}
                persona={persona}
                isSelected={selectedPersona?.agent_name === persona.agent_name}
                onClick={() =>
                  setSelectedPersona(
                    selectedPersona?.agent_name === persona.agent_name ? null : persona,
                  )
                }
                onEdit={() => handleEdit(persona)}
                formatDate={formatDate}
              />
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredPersonas.map((persona) => (
              <PersonaRow
                key={persona.agent_name}
                persona={persona}
                isSelected={selectedPersona?.agent_name === persona.agent_name}
                onClick={() =>
                  setSelectedPersona(
                    selectedPersona?.agent_name === persona.agent_name ? null : persona,
                  )
                }
                onEdit={() => handleEdit(persona)}
                formatDate={formatDate}
              />
            ))}
          </div>
        )}
      </div>

      {/* Detail Panel */}
      {selectedPersona && !editingPersona && (
        <PersonaDetailPanel
          persona={selectedPersona}
          onClose={() => setSelectedPersona(null)}
          onEdit={() => handleEdit(selectedPersona)}
          onDelete={() => handleDelete(selectedPersona.agent_name)}
          formatDate={formatDate}
        />
      )}

      {/* Edit Modal */}
      {editingPersona && (
        <PersonaEditModal
          persona={editingPersona}
          options={options}
          isNew={isCreating}
          saving={saving}
          onChange={setEditingPersona}
          onSave={handleSave}
          onCancel={() => {
            setEditingPersona(null);
            setIsCreating(false);
          }}
        />
      )}
    </div>
  );
}

interface PersonaCardProps {
  persona: Persona;
  isSelected: boolean;
  onClick: () => void;
  onEdit: () => void;
  formatDate: (d: string) => string;
}

function PersonaCard({ persona, isSelected, onClick, onEdit, formatDate }: PersonaCardProps) {
  const expertiseKeys = Object.keys(persona.expertise || {}).slice(0, 3);
  const expertiseCount = Object.keys(persona.expertise || {}).length;

  return (
    <div
      onClick={onClick}
      className={`p-4 border cursor-pointer transition-all ${
        isSelected
          ? 'border-[var(--accent)] bg-[var(--accent)]/10'
          : 'border-border hover:border-[var(--accent)]/40 bg-bg/30'
      }`}
    >
      <div className="flex items-start justify-between mb-3">
        <span className="text-sm font-theme-data text-[var(--acid-cyan)] font-medium">
          {persona.agent_name}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onEdit();
            }}
            className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
          >
            [EDIT]
          </button>
          <span className="text-xs font-theme-data text-text-muted">
            {formatDate(persona.updated_at)}
          </span>
        </div>
      </div>

      <p className="text-xs font-theme-data text-text-primary mb-3 line-clamp-2">
        {persona.description || 'No description'}
      </p>

      {persona.traits.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {persona.traits.slice(0, 3).map((trait) => (
            <span
              key={trait}
              className="px-1.5 py-0.5 text-xs font-theme-data bg-purple/10 text-purple border border-purple/30"
            >
              {trait}
            </span>
          ))}
          {persona.traits.length > 3 && (
            <span className="px-1.5 py-0.5 text-xs font-theme-data text-text-muted">
              +{persona.traits.length - 3}
            </span>
          )}
        </div>
      )}

      {expertiseKeys.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {expertiseKeys.map((exp) => (
            <span
              key={exp}
              className="px-1.5 py-0.5 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30"
            >
              {exp}
            </span>
          ))}
          {expertiseCount > 3 && (
            <span className="px-1.5 py-0.5 text-xs font-theme-data text-text-muted">
              +{expertiseCount - 3}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

interface PersonaRowProps {
  persona: Persona;
  isSelected: boolean;
  onClick: () => void;
  onEdit: () => void;
  formatDate: (d: string) => string;
}

function PersonaRow({ persona, isSelected, onClick, onEdit, formatDate }: PersonaRowProps) {
  const expertiseCount = Object.keys(persona.expertise || {}).length;

  return (
    <div
      onClick={onClick}
      className={`p-3 border cursor-pointer transition-all flex items-center gap-4 ${
        isSelected
          ? 'border-[var(--accent)] bg-[var(--accent)]/10'
          : 'border-border hover:border-[var(--accent)]/40 bg-bg/30'
      }`}
    >
      <div className="flex-shrink-0 w-32">
        <span className="text-sm font-theme-data text-[var(--acid-cyan)] font-medium">
          {persona.agent_name}
        </span>
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-xs font-theme-data text-text-primary truncate">
          {persona.description || 'No description'}
        </p>
      </div>

      <div className="flex-shrink-0 flex items-center gap-2">
        <span className="text-xs font-theme-data text-purple">{persona.traits.length} traits</span>
        <span className="text-xs font-theme-data text-[var(--accent)]">
          {expertiseCount} expertise
        </span>
      </div>

      <button
        onClick={(e) => {
          e.stopPropagation();
          onEdit();
        }}
        className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
      >
        [EDIT]
      </button>

      <div className="flex-shrink-0 w-24 text-right">
        <span className="text-xs font-theme-data text-text-muted">
          {formatDate(persona.updated_at)}
        </span>
      </div>
    </div>
  );
}

interface PersonaDetailPanelProps {
  persona: Persona;
  onClose: () => void;
  onEdit: () => void;
  onDelete: () => void;
  formatDate: (d: string) => string;
}

function PersonaDetailPanel({
  persona,
  onClose,
  onEdit,
  onDelete,
  formatDate,
}: PersonaDetailPanelProps) {
  const expertiseEntries = Object.entries(persona.expertise || {});

  return (
    <div className="border-t border-[var(--accent)]/20 bg-bg/50 p-4">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
          PERSONA DETAILS: {persona.agent_name}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={onEdit}
            className="px-2 py-1 text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] border border-[var(--acid-cyan)]/40 hover:border-[var(--accent)]/40 transition-colors"
          >
            EDIT
          </button>
          <button
            onClick={onDelete}
            className="px-2 py-1 text-xs font-theme-data text-[var(--crimson)] hover:bg-[var(--crimson)]/10 border border-[var(--crimson)]/40 transition-colors"
          >
            DELETE
          </button>
          <button
            onClick={onClose}
            className="px-2 py-1 text-xs font-theme-data text-text-muted hover:text-[var(--crimson)] border border-border hover:border-[var(--crimson)]/40 transition-colors"
          >
            CLOSE
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <h4 className="text-xs font-theme-data text-text-muted mb-2">DESCRIPTION</h4>
          <p className="text-xs font-theme-data text-text-primary bg-surface p-3 border border-border">
            {persona.description || 'No description provided'}
          </p>
        </div>

        <div className="space-y-4">
          <div>
            <h4 className="text-xs font-theme-data text-text-muted mb-2">TRAITS</h4>
            <div className="flex flex-wrap gap-1">
              {persona.traits.length > 0 ? (
                persona.traits.map((trait) => (
                  <span
                    key={trait}
                    className="px-2 py-1 text-xs font-theme-data bg-purple/10 text-purple border border-purple/30"
                  >
                    {trait}
                  </span>
                ))
              ) : (
                <span className="text-xs font-theme-data text-text-muted">No traits defined</span>
              )}
            </div>
          </div>

          <div>
            <h4 className="text-xs font-theme-data text-text-muted mb-2">EXPERTISE</h4>
            <div className="flex flex-wrap gap-1">
              {expertiseEntries.length > 0 ? (
                expertiseEntries.map(([domain, score]) => (
                  <span
                    key={domain}
                    className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30"
                    title={`Score: ${(score as number).toFixed(2)}`}
                  >
                    {domain}
                  </span>
                ))
              ) : (
                <span className="text-xs font-theme-data text-text-muted">
                  No expertise defined
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-border flex gap-6">
        <div>
          <span className="text-xs font-theme-data text-text-muted">CREATED: </span>
          <span className="text-xs font-theme-data text-text-primary">
            {formatDate(persona.created_at)}
          </span>
        </div>
        <div>
          <span className="text-xs font-theme-data text-text-muted">UPDATED: </span>
          <span className="text-xs font-theme-data text-text-primary">
            {formatDate(persona.updated_at)}
          </span>
        </div>
      </div>
    </div>
  );
}

interface PersonaEditModalProps {
  persona: Persona;
  options: PersonaOptions | null;
  isNew: boolean;
  saving: boolean;
  onChange: (persona: Persona) => void;
  onSave: () => void;
  onCancel: () => void;
}

function PersonaEditModal({
  persona,
  options,
  isNew,
  saving,
  onChange,
  onSave,
  onCancel,
}: PersonaEditModalProps) {
  const availableTraits = options?.traits || [];
  const availableDomains = options?.expertise_domains || [];

  const toggleTrait = (trait: string) => {
    const newTraits = persona.traits.includes(trait)
      ? persona.traits.filter((t) => t !== trait)
      : [...persona.traits, trait];
    onChange({ ...persona, traits: newTraits });
  };

  const toggleDomain = (domain: string) => {
    const newExpertise = { ...persona.expertise };
    if (domain in newExpertise) {
      delete newExpertise[domain];
    } else {
      newExpertise[domain] = 0.5;
    }
    onChange({ ...persona, expertise: newExpertise });
  };

  return (
    <div className="fixed inset-0 bg-bg/80 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-[var(--accent)]/40 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between sticky top-0">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
            {isNew ? '+ CREATE PERSONA' : `EDIT: ${persona.agent_name}`}
          </span>
          <button
            onClick={onCancel}
            className="text-xs font-theme-data text-text-muted hover:text-[var(--crimson)]"
          >
            [X]
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Agent Name (only editable on create) */}
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1">
              AGENT NAME *
            </label>
            <input
              type="text"
              value={persona.agent_name}
              onChange={(e) => onChange({ ...persona, agent_name: e.target.value })}
              disabled={!isNew}
              placeholder="e.g., claude, gpt4, mistral"
              className={`w-full bg-bg border border-border px-3 py-2 text-xs font-theme-data text-text-primary placeholder-text-muted focus:border-[var(--accent)]/50 focus:outline-none ${
                !isNew ? 'opacity-50 cursor-not-allowed' : ''
              }`}
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1">
              DESCRIPTION
            </label>
            <textarea
              value={persona.description}
              onChange={(e) => onChange({ ...persona, description: e.target.value })}
              placeholder="Describe this agent's personality and approach..."
              rows={3}
              className="w-full bg-bg border border-border px-3 py-2 text-xs font-theme-data text-text-primary placeholder-text-muted focus:border-[var(--accent)]/50 focus:outline-none resize-none"
            />
          </div>

          {/* Traits */}
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-2">
              PERSONALITY TRAITS ({persona.traits.length} selected)
            </label>
            <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto p-2 bg-bg border border-border">
              {availableTraits.map((trait) => (
                <button
                  key={trait}
                  onClick={() => toggleTrait(trait)}
                  className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                    persona.traits.includes(trait)
                      ? 'bg-purple/20 text-purple border-purple/50'
                      : 'text-text-muted border-border hover:border-purple/30'
                  }`}
                >
                  {trait}
                </button>
              ))}
            </div>
          </div>

          {/* Expertise */}
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-2">
              EXPERTISE DOMAINS ({Object.keys(persona.expertise).length} selected)
            </label>
            <div className="flex flex-wrap gap-2 max-h-48 overflow-y-auto p-2 bg-bg border border-border">
              {availableDomains.map((domain) => (
                <button
                  key={domain}
                  onClick={() => toggleDomain(domain)}
                  className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                    domain in persona.expertise
                      ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/50'
                      : 'text-text-muted border-border hover:border-[var(--accent)]/30'
                  }`}
                >
                  {domain}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-[var(--accent)]/20 bg-bg/50 flex items-center justify-end gap-2 sticky bottom-0">
          <button
            onClick={onCancel}
            disabled={saving}
            className="px-4 py-2 text-xs font-theme-data text-text-muted border border-border hover:border-[var(--crimson)]/40 hover:text-[var(--crimson)] transition-colors disabled:opacity-50"
          >
            CANCEL
          </button>
          <button
            onClick={onSave}
            disabled={saving || !persona.agent_name.trim()}
            className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40 hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? 'SAVING...' : 'SAVE'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default PersonaEditor;
