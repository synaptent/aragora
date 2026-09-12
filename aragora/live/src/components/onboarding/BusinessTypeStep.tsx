'use client';

import { useState } from 'react';

export type BusinessType =
  | 'retail'
  | 'saas'
  | 'professional_services'
  | 'manufacturing'
  | 'healthcare'
  | 'finance'
  | 'other';

interface BusinessTypeStepProps {
  selectedType: BusinessType | null;
  onSelect: (type: BusinessType) => void;
}

const BUSINESS_TYPES: Array<{
  type: BusinessType;
  icon: string;
  title: string;
  description: string;
  examples: string;
}> = [
  {
    type: 'saas',
    icon: '☁️',
    title: 'SaaS / Tech',
    description: 'Software and technology companies',
    examples: 'Feature prioritization, architecture decisions, security reviews',
  },
  {
    type: 'professional_services',
    icon: '💼',
    title: 'Professional Services',
    description: 'Consulting, legal, accounting firms',
    examples: 'Client proposals, resource allocation, policy reviews',
  },
  {
    type: 'retail',
    icon: '🛒',
    title: 'Retail / E-commerce',
    description: 'Physical or online stores',
    examples: 'Inventory decisions, pricing strategy, vendor selection',
  },
  {
    type: 'manufacturing',
    icon: '🏭',
    title: 'Manufacturing',
    description: 'Production and supply chain',
    examples: 'Process optimization, quality control, supplier evaluation',
  },
  {
    type: 'healthcare',
    icon: '🏥',
    title: 'Healthcare',
    description: 'Medical and health services',
    examples: 'Compliance reviews, protocol decisions, vendor assessment',
  },
  {
    type: 'finance',
    icon: '🏦',
    title: 'Finance',
    description: 'Banking, insurance, investment',
    examples: 'Risk assessment, policy review, compliance decisions',
  },
  {
    type: 'other',
    icon: '🌐',
    title: 'Other',
    description: 'Another industry or general use',
    examples: 'Team decisions, strategic planning, vendor evaluation',
  },
];

export function BusinessTypeStep({ selectedType, onSelect }: BusinessTypeStepProps) {
  const [hoveredType, setHoveredType] = useState<BusinessType | null>(null);

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h3 className="text-xl font-theme-data text-[var(--accent)] mb-2">
          What industry are you in?
        </h3>
        <p className="text-sm text-text-muted">
          We&apos;ll customize your experience with relevant templates and workflows
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {BUSINESS_TYPES.map((business) => (
          <button
            key={business.type}
            onClick={() => onSelect(business.type)}
            onMouseEnter={() => setHoveredType(business.type)}
            onMouseLeave={() => setHoveredType(null)}
            className={`p-4 border rounded-lg text-left transition-all ${
              selectedType === business.type
                ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                : 'border-border hover:border-[var(--accent)]/50'
            }`}
          >
            <div className="flex items-start gap-3">
              <span className="text-2xl">{business.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="font-theme-data text-sm text-text">{business.title}</div>
                <div className="text-xs text-text-muted mt-1">{business.description}</div>
              </div>
              {selectedType === business.type && (
                <span className="text-[var(--accent)] text-lg">✓</span>
              )}
            </div>
          </button>
        ))}
      </div>

      {(selectedType || hoveredType) && (
        <div className="p-4 bg-surface border border-border rounded-lg">
          <div className="text-xs text-text-muted mb-1">Example use cases:</div>
          <div className="text-sm text-text">
            {BUSINESS_TYPES.find((b) => b.type === (hoveredType || selectedType))?.examples}
          </div>
        </div>
      )}

      <div className="text-center">
        <p className="text-xs text-text-muted">You can always change this later in Settings</p>
      </div>
    </div>
  );
}
