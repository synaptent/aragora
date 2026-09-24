'use client';

import { useOnboardingStore } from '@/store';

const TEAM_SIZES = [
  { value: '1-5', label: '1-5 people' },
  { value: '6-15', label: '6-15 people' },
  { value: '16-50', label: '16-50 people' },
  { value: '50+', label: '50+ people' },
] as const;

const USE_CASES = [
  { value: 'team_decisions', label: 'Team Decisions', description: 'Quick yes/no decisions' },
  { value: 'project_planning', label: 'Project Planning', description: 'Feature prioritization' },
  { value: 'vendor_selection', label: 'Vendor Selection', description: 'Compare options' },
  { value: 'policy_review', label: 'Policy Review', description: 'Compliance checks' },
  {
    value: 'technical_decisions',
    label: 'Technical Decisions',
    description: 'Architecture reviews',
  },
  { value: 'general', label: 'Just Exploring', description: 'See how it works' },
] as const;

export function OrgSetupStep() {
  const {
    organizationName,
    organizationSlug,
    teamSize,
    useCase,
    setOrganizationName,
    setOrganizationSlug,
    setTeamSize,
    setUseCase,
  } = useOnboardingStore();

  const handleNameChange = (name: string) => {
    setOrganizationName(name);
    // Auto-generate slug from name
    const slug = name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
    setOrganizationSlug(slug);
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-theme-data text-[var(--accent)] mb-2">Set Up Your Workspace</h3>
        <p className="text-sm text-text-muted">Create a workspace for your team</p>
      </div>

      {/* Organization Name */}
      <div>
        <label className="block text-sm font-theme-data text-text mb-2">Organization Name *</label>
        <input
          type="text"
          value={organizationName}
          onChange={(e) => handleNameChange(e.target.value)}
          placeholder="Acme Corp"
          className="w-full px-4 py-2 bg-bg border border-[var(--accent)]/30 rounded text-text font-theme-data focus:border-[var(--accent)] focus:outline-none"
        />
        {organizationSlug && (
          <p className="text-xs text-text-muted mt-1">
            Workspace URL: aragora.ai/{organizationSlug}
          </p>
        )}
      </div>

      {/* Team Size */}
      <div>
        <label className="block text-sm font-theme-data text-text mb-2">Team Size *</label>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {TEAM_SIZES.map((size) => (
            <button
              key={size.value}
              onClick={() => setTeamSize(size.value)}
              className={`px-3 py-2 border rounded text-sm font-theme-data transition-colors ${
                teamSize === size.value
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:border-[var(--accent)]/50'
              }`}
            >
              {size.label}
            </button>
          ))}
        </div>
      </div>

      {/* Use Case */}
      <div>
        <label className="block text-sm font-theme-data text-text mb-2">Primary Use Case</label>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {USE_CASES.map((uc) => (
            <button
              key={uc.value}
              onClick={() => setUseCase(uc.value)}
              className={`px-3 py-2 border rounded text-left transition-colors ${
                useCase === uc.value
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                  : 'border-[var(--accent)]/30 hover:border-[var(--accent)]/50'
              }`}
            >
              <div
                className={`text-sm font-theme-data ${useCase === uc.value ? 'text-[var(--accent)]' : 'text-text'}`}
              >
                {uc.label}
              </div>
              <div className="text-xs text-text-muted">{uc.description}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
