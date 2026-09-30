'use client';

import { useState } from 'react';
import type { Workspace } from './WorkspaceManager';

export interface WorkspaceSettingsProps {
  workspace: Workspace;
  onSave?: (workspace: Workspace) => void;
  onDelete?: () => void;
  className?: string;
}

const VERTICALS = [
  { id: 'software', name: 'Software Engineering', icon: '&#x1F4BB;' },
  { id: 'legal', name: 'Legal', icon: '&#x2696;' },
  { id: 'healthcare', name: 'Healthcare', icon: '&#x1F3E5;' },
  { id: 'accounting', name: 'Accounting & Finance', icon: '&#x1F4CA;' },
  { id: 'research', name: 'Research', icon: '&#x1F52C;' },
];

const COMPLIANCE_FRAMEWORKS = [
  { id: 'owasp', name: 'OWASP', vertical: 'software' },
  { id: 'cwe', name: 'CWE', vertical: 'software' },
  { id: 'gdpr', name: 'GDPR', vertical: 'legal' },
  { id: 'ccpa', name: 'CCPA', vertical: 'legal' },
  { id: 'hipaa', name: 'HIPAA', vertical: 'healthcare' },
  { id: 'hitech', name: 'HITECH', vertical: 'healthcare' },
  { id: 'sox', name: 'SOX', vertical: 'accounting' },
  { id: 'gaap', name: 'GAAP', vertical: 'accounting' },
  { id: 'irb', name: 'IRB', vertical: 'research' },
  { id: 'consort', name: 'CONSORT', vertical: 'research' },
];

export function WorkspaceSettings({
  workspace,
  onSave,
  onDelete,
  className = '',
}: WorkspaceSettingsProps) {
  const [name, setName] = useState(workspace.name);
  const [description, setDescription] = useState(workspace.description);
  const [defaultVertical, setDefaultVertical] = useState(workspace.settings.defaultVertical || '');
  const [selectedFrameworks, setSelectedFrameworks] = useState<string[]>(
    workspace.settings.complianceFrameworks,
  );
  const [agentLimit, setAgentLimit] = useState(workspace.settings.agentLimit);
  const [documentsQuota, setDocumentsQuota] = useState(workspace.settings.documentsQuota);
  const [hasChanges, setHasChanges] = useState(false);

  const handleChange = () => {
    setHasChanges(true);
  };

  const toggleFramework = (framework: string) => {
    setSelectedFrameworks((prev) =>
      prev.includes(framework) ? prev.filter((f) => f !== framework) : [...prev, framework],
    );
    handleChange();
  };

  const handleSave = () => {
    const updated: Workspace = {
      ...workspace,
      name,
      description,
      updatedAt: new Date().toISOString(),
      settings: {
        ...workspace.settings,
        defaultVertical,
        complianceFrameworks: selectedFrameworks,
        agentLimit,
        documentsQuota,
      },
    };
    onSave?.(updated);
    setHasChanges(false);
  };

  const availableFrameworks = COMPLIANCE_FRAMEWORKS.filter(
    (fw) => !defaultVertical || fw.vertical === defaultVertical,
  );

  return (
    <div className={className}>
      <div className="space-y-6">
        {/* Basic Settings */}
        <div>
          <h4 className="font-theme-data font-bold text-text mb-4">Basic Settings</h4>
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                WORKSPACE NAME
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  handleChange();
                }}
                className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                DESCRIPTION
              </label>
              <textarea
                value={description}
                onChange={(e) => {
                  setDescription(e.target.value);
                  handleChange();
                }}
                rows={3}
                className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)] resize-none"
              />
            </div>
          </div>
        </div>

        {/* Vertical Settings */}
        <div>
          <h4 className="font-theme-data font-bold text-text mb-4">Default Vertical</h4>
          <div className="grid grid-cols-5 gap-2">
            {VERTICALS.map((vertical) => (
              <button
                key={vertical.id}
                onClick={() => {
                  setDefaultVertical(vertical.id);
                  handleChange();
                }}
                className={`
                  p-3 rounded-lg border-2 transition-all flex flex-col items-center gap-2
                  ${
                    defaultVertical === vertical.id
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                      : 'border-border hover:border-text-muted bg-bg'
                  }
                `}
              >
                <span className="text-xl" dangerouslySetInnerHTML={{ __html: vertical.icon }} />
                <span className="text-xs font-theme-data text-center">{vertical.name}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Compliance Frameworks */}
        <div>
          <h4 className="font-theme-data font-bold text-text mb-4">Compliance Frameworks</h4>
          <div className="flex flex-wrap gap-2">
            {availableFrameworks.map((framework) => (
              <button
                key={framework.id}
                onClick={() => toggleFramework(framework.name)}
                className={`
                  px-3 py-1.5 text-xs font-theme-data rounded-lg border transition-all
                  ${
                    selectedFrameworks.includes(framework.name)
                      ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                      : 'border-border hover:border-text-muted text-text-muted'
                  }
                `}
              >
                {framework.name}
              </button>
            ))}
          </div>
        </div>

        {/* Quotas */}
        <div>
          <h4 className="font-theme-data font-bold text-text mb-4">Quotas & Limits</h4>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                AGENT LIMIT
              </label>
              <select
                value={agentLimit}
                onChange={(e) => {
                  setAgentLimit(Number(e.target.value));
                  handleChange();
                }}
                className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              >
                <option value="5">5 agents</option>
                <option value="10">10 agents</option>
                <option value="20">20 agents</option>
                <option value="50">50 agents</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                DOCUMENTS QUOTA
              </label>
              <select
                value={documentsQuota}
                onChange={(e) => {
                  setDocumentsQuota(Number(e.target.value));
                  handleChange();
                }}
                className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              >
                <option value="1000">1,000 documents</option>
                <option value="5000">5,000 documents</option>
                <option value="10000">10,000 documents</option>
                <option value="50000">50,000 documents</option>
                <option value="100000">100,000 documents</option>
              </select>
            </div>
          </div>
          <div className="mt-3 p-3 bg-bg border border-border rounded">
            <div className="flex items-center justify-between text-xs mb-2">
              <span className="text-text-muted">Current Usage:</span>
              <span className="font-theme-data text-text">
                {workspace.settings.documentsUsed.toLocaleString()} /{' '}
                {documentsQuota.toLocaleString()}
              </span>
            </div>
            <div className="h-2 bg-surface rounded-full overflow-hidden">
              <div
                className="h-full bg-[var(--accent)] transition-all"
                style={{
                  width: `${Math.min(100, (workspace.settings.documentsUsed / documentsQuota) * 100)}%`,
                }}
              />
            </div>
          </div>
        </div>

        {/* Danger Zone */}
        <div className="border-t border-border pt-6">
          <h4 className="font-theme-data font-bold text-red-400 mb-4">Danger Zone</h4>
          <div className="p-4 bg-red-900/10 border border-red-800/30 rounded-lg">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-theme-data text-sm text-text">Delete Workspace</p>
                <p className="text-xs text-text-muted mt-1">
                  This will permanently delete the workspace and all its data.
                </p>
              </div>
              <button
                onClick={onDelete}
                className="px-4 py-2 text-xs font-theme-data bg-red-900/30 text-red-400 border border-red-800/30 rounded hover:bg-red-900/50 transition-colors"
              >
                DELETE
              </button>
            </div>
          </div>
        </div>

        {/* Save Button */}
        {hasChanges && (
          <div className="sticky bottom-0 py-4 bg-surface border-t border-border -mx-4 px-4">
            <button
              onClick={handleSave}
              className="w-full px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors"
            >
              SAVE CHANGES
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
