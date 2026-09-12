'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/context/AuthContext';

/**
 * Industry vertical configuration for specialized debate agents.
 *
 * Verticals provide domain-specific expertise, compliance frameworks,
 * and recommended agent configurations for specialized debates.
 */
export interface Vertical {
  id: string;
  displayName: string;
  description: string;
  icon: string;
  expertiseAreas: string[];
  complianceFrameworks: string[];
  suggestedAgents: string[];
  costTier: 'standard' | 'professional' | 'enterprise';
  keywords: string[];
  /** Persona configurations for this vertical */
  personas?: PersonaConfig[];
}

/**
 * Persona configuration for vertical-specific agent behavior.
 */
export interface PersonaConfig {
  id: string;
  name: string;
  role: string;
  traits: string[];
  suitability: number; // 0-1 score for task matching
}

// Industry verticals with specialized configurations
const INDUSTRY_VERTICALS: Vertical[] = [
  {
    id: 'general',
    displayName: 'General',
    description: 'Multi-purpose debate for any topic',
    icon: '\u2699\uFE0F', // Gear
    expertiseAreas: ['Reasoning', 'Analysis', 'Problem-solving'],
    complianceFrameworks: [],
    suggestedAgents: ['claude', 'gpt', 'deepseek'],
    costTier: 'standard',
    keywords: [],
    personas: [
      {
        id: 'analyst',
        name: 'Analyst',
        role: 'Critical analysis',
        traits: ['logical', 'thorough'],
        suitability: 0.8,
      },
      {
        id: 'synthesizer',
        name: 'Synthesizer',
        role: 'Integration',
        traits: ['holistic', 'creative'],
        suitability: 0.8,
      },
    ],
  },
  {
    id: 'software',
    displayName: 'Software Engineering',
    description: 'Code review, architecture, security analysis',
    icon: '\uD83D\uDCBB', // Laptop
    expertiseAreas: ['Architecture', 'Code Review', 'Security', 'Performance', 'Testing'],
    complianceFrameworks: ['OWASP', 'CWE', 'SANS'],
    suggestedAgents: ['claude', 'deepseek', 'codestral'],
    costTier: 'professional',
    keywords: [
      'code',
      'api',
      'software',
      'bug',
      'function',
      'programming',
      'typescript',
      'python',
      'architecture',
      'database',
    ],
    personas: [
      {
        id: 'architect',
        name: 'Architect',
        role: 'System design',
        traits: ['strategic', 'scalability-focused'],
        suitability: 0.95,
      },
      {
        id: 'security-eng',
        name: 'Security Engineer',
        role: 'Vulnerability analysis',
        traits: ['paranoid', 'thorough'],
        suitability: 0.9,
      },
      {
        id: 'reviewer',
        name: 'Code Reviewer',
        role: 'Quality assurance',
        traits: ['detail-oriented', 'best-practices'],
        suitability: 0.85,
      },
    ],
  },
  {
    id: 'legal',
    displayName: 'Legal & Compliance',
    description: 'Contract review, regulatory analysis, compliance',
    icon: '\u2696\uFE0F', // Balance scale
    expertiseAreas: ['Contract Analysis', 'Regulatory', 'Risk Assessment', 'IP'],
    complianceFrameworks: ['GDPR', 'SOX', 'HIPAA', 'PCI-DSS', 'CCPA'],
    suggestedAgents: ['claude', 'gpt-4o', 'gemini'],
    costTier: 'enterprise',
    keywords: [
      'legal',
      'contract',
      'compliance',
      'regulation',
      'law',
      'liability',
      'terms',
      'privacy',
      'gdpr',
    ],
    personas: [
      {
        id: 'contract-analyst',
        name: 'Contract Analyst',
        role: 'Document review',
        traits: ['meticulous', 'risk-aware'],
        suitability: 0.95,
      },
      {
        id: 'compliance-officer',
        name: 'Compliance Officer',
        role: 'Regulatory guidance',
        traits: ['regulatory-expert', 'cautious'],
        suitability: 0.9,
      },
      {
        id: 'ip-counsel',
        name: 'IP Counsel',
        role: 'Intellectual property',
        traits: ['protective', 'strategic'],
        suitability: 0.85,
      },
    ],
  },
  {
    id: 'healthcare',
    displayName: 'Healthcare',
    description: 'Clinical analysis, medical research, health policy',
    icon: '\uD83C\uDFE5', // Hospital
    expertiseAreas: ['Clinical', 'Research', 'Policy', 'Bioethics'],
    complianceFrameworks: ['HIPAA', 'FDA', 'HL7 FHIR', '21 CFR Part 11'],
    suggestedAgents: ['claude', 'gpt-4o', 'gemini'],
    costTier: 'enterprise',
    keywords: [
      'health',
      'medical',
      'clinical',
      'patient',
      'treatment',
      'diagnosis',
      'healthcare',
      'hipaa',
      'fda',
    ],
    personas: [
      {
        id: 'clinical-analyst',
        name: 'Clinical Analyst',
        role: 'Medical review',
        traits: ['evidence-based', 'patient-focused'],
        suitability: 0.95,
      },
      {
        id: 'bioethicist',
        name: 'Bioethicist',
        role: 'Ethics review',
        traits: ['principled', 'balanced'],
        suitability: 0.9,
      },
      {
        id: 'researcher',
        name: 'Medical Researcher',
        role: 'Literature synthesis',
        traits: ['thorough', 'critical'],
        suitability: 0.85,
      },
    ],
  },
  {
    id: 'fintech',
    displayName: 'FinTech & Banking',
    description: 'Payments, trading systems, regulatory compliance',
    icon: '\uD83C\uDFE6', // Bank
    expertiseAreas: ['Payments', 'Trading', 'Risk Management', 'Regulatory', 'Fraud Detection'],
    complianceFrameworks: ['PCI-DSS', 'SOC2', 'AML/KYC', 'MiFID II', 'Basel III'],
    suggestedAgents: ['claude', 'gpt-4o', 'deepseek'],
    costTier: 'enterprise',
    keywords: [
      'payment',
      'trading',
      'bank',
      'fintech',
      'transaction',
      'fraud',
      'kyc',
      'aml',
      'pci',
    ],
    personas: [
      {
        id: 'risk-analyst',
        name: 'Risk Analyst',
        role: 'Risk assessment',
        traits: ['quantitative', 'cautious'],
        suitability: 0.95,
      },
      {
        id: 'compliance-specialist',
        name: 'Compliance Specialist',
        role: 'Regulatory adherence',
        traits: ['regulatory-expert', 'detail-oriented'],
        suitability: 0.9,
      },
      {
        id: 'fraud-analyst',
        name: 'Fraud Analyst',
        role: 'Threat detection',
        traits: ['pattern-recognition', 'suspicious'],
        suitability: 0.85,
      },
    ],
  },
  {
    id: 'accounting',
    displayName: 'Accounting & Audit',
    description: 'Financial analysis, audit, tax planning',
    icon: '\uD83D\uDCB0', // Money bag
    expertiseAreas: ['Audit', 'Tax', 'Financial Analysis', 'Reporting', 'Internal Controls'],
    complianceFrameworks: ['SOX', 'GAAP', 'IFRS', 'PCAOB'],
    suggestedAgents: ['claude', 'gpt-4o', 'gemini'],
    costTier: 'professional',
    keywords: ['finance', 'accounting', 'tax', 'audit', 'budget', 'revenue', 'cost', 'sox', 'gaap'],
    personas: [
      {
        id: 'auditor',
        name: 'Auditor',
        role: 'Compliance verification',
        traits: ['skeptical', 'methodical'],
        suitability: 0.95,
      },
      {
        id: 'tax-advisor',
        name: 'Tax Advisor',
        role: 'Tax strategy',
        traits: ['optimization-focused', 'regulatory-aware'],
        suitability: 0.9,
      },
      {
        id: 'financial-analyst',
        name: 'Financial Analyst',
        role: 'Financial modeling',
        traits: ['quantitative', 'forward-looking'],
        suitability: 0.85,
      },
    ],
  },
  {
    id: 'academic',
    displayName: 'Academic Research',
    description: 'Scientific analysis, literature review, methodology',
    icon: '\uD83C\uDF93', // Graduation cap
    expertiseAreas: [
      'Research Methods',
      'Literature Review',
      'Data Analysis',
      'Peer Review',
      'Ethics',
    ],
    complianceFrameworks: ['IRB', 'NIH Guidelines', 'CONSORT', 'PRISMA'],
    suggestedAgents: ['claude', 'gpt-4o', 'gemini'],
    costTier: 'professional',
    keywords: [
      'research',
      'study',
      'analysis',
      'data',
      'hypothesis',
      'methodology',
      'academic',
      'peer-review',
      'publication',
    ],
    personas: [
      {
        id: 'methodologist',
        name: 'Methodologist',
        role: 'Research design',
        traits: ['rigorous', 'systematic'],
        suitability: 0.95,
      },
      {
        id: 'statistician',
        name: 'Statistician',
        role: 'Data analysis',
        traits: ['quantitative', 'precise'],
        suitability: 0.9,
      },
      {
        id: 'peer-reviewer',
        name: 'Peer Reviewer',
        role: 'Critical assessment',
        traits: ['constructive', 'thorough'],
        suitability: 0.85,
      },
    ],
  },
];

// Cost tier styling
const COST_TIER_STYLES = {
  standard: {
    label: 'Standard',
    color: 'text-[var(--accent)]',
    bgColor: 'bg-[var(--accent)]/10',
    borderColor: 'border-[var(--accent)]/30',
  },
  professional: {
    label: 'Pro',
    color: 'text-[var(--acid-cyan)]',
    bgColor: 'bg-[var(--acid-cyan)]/10',
    borderColor: 'border-[var(--acid-cyan)]/30',
  },
  enterprise: {
    label: 'Enterprise',
    color: 'text-warning',
    bgColor: 'bg-warning/10',
    borderColor: 'border-warning/30',
  },
};

interface VerticalSelectorProps {
  apiBase: string;
  selectedVertical: string;
  onVerticalChange: (verticalId: string) => void;
  onAgentsChange?: (agents: string) => void;
  questionText?: string;
  compact?: boolean;
}

export function VerticalSelector({
  apiBase,
  selectedVertical,
  onVerticalChange,
  onAgentsChange,
  questionText = '',
  compact = false,
}: VerticalSelectorProps) {
  const { isAuthenticated, isLoading: authLoading, tokens } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [suggestedVertical, setSuggestedVertical] = useState<string | null>(null);
  const [_loadingBackend, setLoadingBackend] = useState(false);

  // Get selected vertical config
  const currentVertical =
    INDUSTRY_VERTICALS.find((v) => v.id === selectedVertical) || INDUSTRY_VERTICALS[0];

  // Auto-detect vertical from question text
  useEffect(() => {
    if (!questionText.trim()) {
      setSuggestedVertical(null);
      return;
    }

    const questionLower = questionText.toLowerCase();
    let bestMatch: string | null = null;
    let bestScore = 0;

    for (const vertical of INDUSTRY_VERTICALS) {
      if (vertical.id === 'general') continue;

      let score = 0;
      for (const keyword of vertical.keywords) {
        if (questionLower.includes(keyword)) {
          score += 1;
        }
      }

      if (score > bestScore) {
        bestScore = score;
        bestMatch = vertical.id;
      }
    }

    // Only suggest if we have at least 2 keyword matches
    setSuggestedVertical(bestScore >= 2 ? bestMatch : null);
  }, [questionText]);

  // Fetch backend verticals (if available and authenticated)
  useEffect(() => {
    // Skip if auth is still loading or not authenticated
    if (authLoading) return;
    if (!isAuthenticated) return;

    const fetchBackendVerticals = async () => {
      try {
        setLoadingBackend(true);
        const headers: HeadersInit = { 'Content-Type': 'application/json' };
        if (tokens?.access_token) {
          headers['Authorization'] = `Bearer ${tokens.access_token}`;
        }
        const response = await fetch(`${apiBase}/api/verticals`, { method: 'GET', headers });

        if (response.ok) {
          // Backend verticals could extend the list
          // For now, we just check if the endpoint exists
        }
      } catch {
        // Backend not available - use client-side verticals only
      } finally {
        setLoadingBackend(false);
      }
    };

    fetchBackendVerticals();
  }, [apiBase, authLoading, isAuthenticated, tokens?.access_token]);

  // Apply suggested agents when vertical changes
  const handleVerticalSelect = useCallback(
    (verticalId: string) => {
      onVerticalChange(verticalId);
      setIsOpen(false);

      const vertical = INDUSTRY_VERTICALS.find((v) => v.id === verticalId);
      if (vertical && onAgentsChange) {
        onAgentsChange(vertical.suggestedAgents.join(','));
      }
    },
    [onVerticalChange, onAgentsChange],
  );

  // Compact mode - just a chip
  if (compact) {
    return (
      <div className="relative inline-block">
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className={`px-2 py-1 text-xs font-theme-data border rounded flex items-center gap-1.5
                     ${COST_TIER_STYLES[currentVertical.costTier].borderColor}
                     hover:border-[var(--accent)]/60 transition-colors`}
        >
          <span>{currentVertical.icon}</span>
          <span className="text-text-muted">{currentVertical.displayName}</span>
          <span className={`text-[10px] ${COST_TIER_STYLES[currentVertical.costTier].color}`}>
            [{COST_TIER_STYLES[currentVertical.costTier].label}]
          </span>
        </button>

        {isOpen && (
          <VerticalDropdown
            verticals={INDUSTRY_VERTICALS}
            selectedId={selectedVertical}
            suggestedId={suggestedVertical}
            onSelect={handleVerticalSelect}
            onClose={() => setIsOpen(false)}
          />
        )}
      </div>
    );
  }

  // Full mode - expanded selector
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="block text-xs font-theme-data text-text-muted">INDUSTRY VERTICAL</label>
        {suggestedVertical && suggestedVertical !== selectedVertical && (
          <button
            type="button"
            onClick={() => handleVerticalSelect(suggestedVertical)}
            className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
          >
            [Detected: {INDUSTRY_VERTICALS.find((v) => v.id === suggestedVertical)?.displayName}]
          </button>
        )}
      </div>

      <div className="relative">
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className="w-full px-4 py-3 bg-bg border border-[var(--accent)]/30 rounded
                     flex items-center justify-between gap-2
                     hover:border-[var(--accent)]/60 transition-colors"
        >
          <div className="flex items-center gap-3">
            <span className="text-xl">{currentVertical.icon}</span>
            <div className="text-left">
              <div className="font-theme-data text-sm text-text">{currentVertical.displayName}</div>
              <div className="text-[10px] text-text-muted">{currentVertical.description}</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Cost tier badge */}
            <span
              className={`px-2 py-0.5 text-[10px] font-theme-data rounded
                            ${COST_TIER_STYLES[currentVertical.costTier].bgColor}
                            ${COST_TIER_STYLES[currentVertical.costTier].color}`}
            >
              {COST_TIER_STYLES[currentVertical.costTier].label}
            </span>

            {/* Dropdown arrow */}
            <span className="text-text-muted">{isOpen ? '\u25B2' : '\u25BC'}</span>
          </div>
        </button>

        {isOpen && (
          <VerticalDropdown
            verticals={INDUSTRY_VERTICALS}
            selectedId={selectedVertical}
            suggestedId={suggestedVertical}
            onSelect={handleVerticalSelect}
            onClose={() => setIsOpen(false)}
            showDetails
          />
        )}
      </div>

      {/* Expertise areas, compliance, and personas */}
      {currentVertical.id !== 'general' && (
        <div className="space-y-2 mt-2">
          <div className="flex flex-wrap gap-2">
            {/* Expertise tags */}
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-text-muted">Expertise:</span>
              {currentVertical.expertiseAreas.slice(0, 3).map((area) => (
                <span
                  key={area}
                  className="px-1.5 py-0.5 text-[10px] font-theme-data bg-surface border border-[var(--accent)]/20 rounded"
                >
                  {area}
                </span>
              ))}
              {currentVertical.expertiseAreas.length > 3 && (
                <span className="text-[10px] text-text-muted">
                  +{currentVertical.expertiseAreas.length - 3}
                </span>
              )}
            </div>

            {/* Compliance frameworks */}
            {currentVertical.complianceFrameworks.length > 0 && (
              <div className="flex items-center gap-1">
                <span className="text-[10px] text-text-muted">Compliance:</span>
                {currentVertical.complianceFrameworks.slice(0, 2).map((framework) => (
                  <span
                    key={framework}
                    className="px-1.5 py-0.5 text-[10px] font-theme-data bg-warning/10 text-warning border border-warning/20 rounded"
                  >
                    {framework}
                  </span>
                ))}
                {currentVertical.complianceFrameworks.length > 2 && (
                  <span className="text-[10px] text-warning/60">
                    +{currentVertical.complianceFrameworks.length - 2}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Persona recommendations */}
          {currentVertical.personas && currentVertical.personas.length > 0 && (
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-text-muted">Personas:</span>
              {currentVertical.personas.slice(0, 3).map((persona) => (
                <span
                  key={persona.id}
                  className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/20 rounded flex items-center gap-1"
                  title={`${persona.role} - ${persona.traits.join(', ')}`}
                >
                  {persona.name}
                  <span className="text-[8px] text-[var(--acid-cyan)]/60">
                    {Math.round(persona.suitability * 100)}%
                  </span>
                </span>
              ))}
            </div>
          )}

          {/* Suggested agents */}
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-text-muted">Agents:</span>
            {currentVertical.suggestedAgents.map((agent) => (
              <span
                key={agent}
                className="px-1.5 py-0.5 text-[10px] font-theme-data bg-bg border border-[var(--accent)]/20 rounded text-text"
              >
                {agent}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface VerticalDropdownProps {
  verticals: Vertical[];
  selectedId: string;
  suggestedId: string | null;
  onSelect: (verticalId: string) => void;
  onClose: () => void;
  showDetails?: boolean;
}

function VerticalDropdown({
  verticals,
  selectedId,
  suggestedId,
  onSelect,
  onClose,
  showDetails = false,
}: VerticalDropdownProps) {
  // Close on escape or click outside
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('.vertical-dropdown')) {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handleClickOutside);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose]);

  return (
    <div
      className="vertical-dropdown absolute top-full left-0 right-0 mt-1 z-50
                 bg-surface border border-[var(--accent)]/30 rounded shadow-lg
                 max-h-[400px] overflow-y-auto"
    >
      {verticals.map((vertical) => {
        const isSelected = vertical.id === selectedId;
        const isSuggested = vertical.id === suggestedId;
        const tierStyle = COST_TIER_STYLES[vertical.costTier];

        return (
          <button
            key={vertical.id}
            type="button"
            onClick={() => onSelect(vertical.id)}
            className={`w-full px-4 py-3 flex items-start gap-3 text-left
                       border-b border-[var(--accent)]/10 last:border-b-0
                       hover:bg-bg transition-colors
                       ${isSelected ? 'bg-[var(--accent)]/10' : ''}`}
          >
            <span className="text-xl flex-shrink-0">{vertical.icon}</span>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-theme-data text-sm text-text">{vertical.displayName}</span>
                {isSuggested && (
                  <span className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] rounded">
                    Suggested
                  </span>
                )}
                {isSelected && <span className="text-[var(--accent)]">\u2713</span>}
              </div>

              <div className="text-[10px] text-text-muted mt-0.5">{vertical.description}</div>

              {showDetails && vertical.id !== 'general' && (
                <div className="space-y-1.5 mt-2">
                  {/* Expertise and compliance */}
                  <div className="flex flex-wrap gap-1">
                    {vertical.expertiseAreas.slice(0, 3).map((area) => (
                      <span
                        key={area}
                        className="px-1 py-0.5 text-[10px] font-theme-data bg-bg rounded text-text-muted"
                      >
                        {area}
                      </span>
                    ))}
                    {vertical.complianceFrameworks.length > 0 && (
                      <span className="px-1 py-0.5 text-[10px] font-theme-data bg-warning/10 text-warning rounded">
                        +{vertical.complianceFrameworks.length} compliance
                      </span>
                    )}
                  </div>
                  {/* Personas */}
                  {vertical.personas && vertical.personas.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      <span className="text-[10px] text-text-muted/60">Personas:</span>
                      {vertical.personas.slice(0, 2).map((persona) => (
                        <span
                          key={persona.id}
                          className="px-1 py-0.5 text-[10px] font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)]/80 rounded"
                          title={persona.role}
                        >
                          {persona.name}
                        </span>
                      ))}
                      {vertical.personas.length > 2 && (
                        <span className="text-[10px] text-[var(--acid-cyan)]/50">
                          +{vertical.personas.length - 2}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            <span
              className={`px-2 py-0.5 text-[10px] font-theme-data rounded flex-shrink-0
                            ${tierStyle.bgColor} ${tierStyle.color}`}
            >
              {tierStyle.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// Export for use in other components
export { INDUSTRY_VERTICALS };
export type { VerticalSelectorProps };
