'use client';

import { useState, useMemo, useCallback } from 'react';

// Pricing tiers for training data export
const PRICING_TIERS = {
  starter: {
    name: 'Starter',
    price: 0,
    pricePerRecord: 0.001,
    includedRecords: 1000,
    features: [
      'Up to 1,000 records/month free',
      'SFT & DPO formats',
      'JSON/JSONL export',
      'Standard quality filters',
    ],
    limits: { maxRecords: 10000, maxExportsPerDay: 10 },
  },
  pro: {
    name: 'Pro',
    price: 49,
    pricePerRecord: 0.0005,
    includedRecords: 50000,
    features: [
      '50,000 records/month included',
      'All export formats',
      'Gauntlet adversarial data',
      'Advanced quality filters',
      'Priority processing',
      'Custom schemas',
    ],
    limits: { maxRecords: 500000, maxExportsPerDay: 100 },
  },
  enterprise: {
    name: 'Enterprise',
    price: null, // Custom pricing
    pricePerRecord: 0.0001,
    includedRecords: 500000,
    features: [
      '500,000+ records/month',
      'Unlimited exports',
      'Custom data pipelines',
      'Dedicated support',
      'SLA guarantees',
      'On-premise option',
      'Compliance certifications',
      'Custom licensing',
    ],
    limits: {
      maxRecords: -1, // Unlimited
      maxExportsPerDay: -1,
    },
  },
} as const;

const FORMAT_PRICING = {
  sft: {
    name: 'Supervised Fine-Tuning',
    multiplier: 1.0,
    description: 'Standard chat/instruction pairs',
  },
  dpo: {
    name: 'Direct Preference Optimization',
    multiplier: 1.5,
    description: 'Preference pairs for RLHF',
  },
  gauntlet: {
    name: 'Gauntlet Adversarial',
    multiplier: 2.0,
    description: 'Red-team attack/defense pairs',
  },
} as const;

interface UsageData {
  recordsExported: number;
  exportsThisMonth: number;
  lastExportDate: string | null;
  tier: keyof typeof PRICING_TIERS;
}

interface TrainingPricingPanelProps {
  currentUsage?: UsageData;
  onSelectTier?: (tier: keyof typeof PRICING_TIERS) => void;
}

export function TrainingPricingPanel({ currentUsage, onSelectTier }: TrainingPricingPanelProps) {
  const [selectedTier, setSelectedTier] = useState<keyof typeof PRICING_TIERS>(
    currentUsage?.tier || 'starter',
  );
  const [estimateRecords, setEstimateRecords] = useState(10000);
  const [estimateFormat, setEstimateFormat] = useState<keyof typeof FORMAT_PRICING>('sft');
  const [showCalculator, setShowCalculator] = useState(false);

  const usage: UsageData = currentUsage || {
    recordsExported: 0,
    exportsThisMonth: 0,
    lastExportDate: null,
    tier: 'starter',
  };

  const tierInfo = PRICING_TIERS[selectedTier];
  const remainingFreeRecords = Math.max(0, tierInfo.includedRecords - usage.recordsExported);

  // Calculate estimated cost
  const estimatedCost = useMemo(() => {
    const tier = PRICING_TIERS[selectedTier];
    const format = FORMAT_PRICING[estimateFormat];
    const billableRecords = Math.max(0, estimateRecords - tier.includedRecords);
    const baseCost = billableRecords * tier.pricePerRecord * format.multiplier;

    return {
      baseCost: baseCost,
      formatMultiplier: format.multiplier,
      billableRecords,
      freeRecords: Math.min(estimateRecords, tier.includedRecords),
      totalCost: tier.price ? tier.price + baseCost : baseCost,
    };
  }, [selectedTier, estimateRecords, estimateFormat]);

  const handleTierSelect = useCallback(
    (tier: keyof typeof PRICING_TIERS) => {
      setSelectedTier(tier);
      onSelectTier?.(tier);
    },
    [onSelectTier],
  );

  return (
    <div className="space-y-6">
      {/* Current Usage Summary */}
      <div className="bg-surface border border-border rounded-lg p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-theme-data text-text">Current Usage</h3>
          <span className="px-2 py-1 bg-[var(--accent)]/20 text-[var(--accent)] text-xs font-theme-data rounded">
            {usage.tier.toUpperCase()}
          </span>
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-text-muted text-xs font-theme-data">RECORDS EXPORTED</p>
            <p className="text-2xl font-theme-data text-text">
              {usage.recordsExported.toLocaleString()}
            </p>
            <p className="text-xs text-text-muted">
              {remainingFreeRecords.toLocaleString()} free remaining
            </p>
          </div>
          <div>
            <p className="text-text-muted text-xs font-theme-data">EXPORTS THIS MONTH</p>
            <p className="text-2xl font-theme-data text-text">{usage.exportsThisMonth}</p>
            <p className="text-xs text-text-muted">
              {tierInfo.limits.maxExportsPerDay === -1
                ? 'Unlimited'
                : `${tierInfo.limits.maxExportsPerDay}/day limit`}
            </p>
          </div>
          <div>
            <p className="text-text-muted text-xs font-theme-data">LAST EXPORT</p>
            <p className="text-lg font-theme-data text-text">
              {usage.lastExportDate ? new Date(usage.lastExportDate).toLocaleDateString() : 'Never'}
            </p>
          </div>
        </div>

        {/* Usage bar */}
        <div className="mt-4">
          <div className="flex justify-between text-xs text-text-muted mb-1">
            <span>Free tier usage</span>
            <span>{Math.round((usage.recordsExported / tierInfo.includedRecords) * 100)}%</span>
          </div>
          <div className="h-2 bg-bg rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--accent)] transition-all"
              style={{
                width: `${Math.min(100, (usage.recordsExported / tierInfo.includedRecords) * 100)}%`,
              }}
            />
          </div>
        </div>
      </div>

      {/* Pricing Tiers */}
      <div>
        <h3 className="text-lg font-theme-data text-text mb-4">Pricing Plans</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {(
            Object.entries(PRICING_TIERS) as [
              keyof typeof PRICING_TIERS,
              (typeof PRICING_TIERS)[keyof typeof PRICING_TIERS],
            ][]
          ).map(([key, tier]) => (
            <div
              key={key}
              onClick={() => handleTierSelect(key)}
              className={`
                p-4 rounded-lg border cursor-pointer transition-all
                ${
                  selectedTier === key
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                    : 'border-border hover:border-[var(--accent)]/50'
                }
              `}
            >
              <div className="flex items-center justify-between mb-3">
                <h4 className="font-theme-data font-bold text-text">{tier.name}</h4>
                {key === 'pro' && (
                  <span className="px-2 py-0.5 bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] text-xs rounded">
                    POPULAR
                  </span>
                )}
              </div>

              <div className="mb-4">
                {tier.price !== null ? (
                  <>
                    <span className="text-3xl font-theme-data text-text">${tier.price}</span>
                    <span className="text-text-muted text-sm">/month</span>
                  </>
                ) : (
                  <span className="text-xl font-theme-data text-text">Custom Pricing</span>
                )}
              </div>

              <div className="space-y-2 mb-4">
                <div className="text-sm">
                  <span className="text-[var(--accent)] font-theme-data">
                    {tier.includedRecords.toLocaleString()}
                  </span>
                  <span className="text-text-muted"> records included</span>
                </div>
                <div className="text-sm text-text-muted">
                  Then ${tier.pricePerRecord.toFixed(4)}/record
                </div>
              </div>

              <ul className="space-y-1">
                {tier.features.slice(0, 4).map((feature, i) => (
                  <li key={i} className="text-xs text-text-muted flex items-start gap-2">
                    <span className="text-[var(--accent)]">+</span>
                    {feature}
                  </li>
                ))}
                {tier.features.length > 4 && (
                  <li className="text-xs text-[var(--acid-cyan)]">
                    +{tier.features.length - 4} more features
                  </li>
                )}
              </ul>

              <button
                className={`
                  w-full mt-4 py-2 rounded font-theme-data text-sm transition-colors
                  ${
                    selectedTier === key
                      ? 'bg-[var(--accent)] text-bg'
                      : 'bg-surface border border-border text-text hover:border-[var(--accent)]/50'
                  }
                `}
              >
                {selectedTier === key
                  ? 'Current Plan'
                  : key === 'enterprise'
                    ? 'Contact Sales'
                    : 'Select Plan'}
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Format Pricing */}
      <div>
        <h3 className="text-lg font-theme-data text-text mb-4">Format Pricing</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {(
            Object.entries(FORMAT_PRICING) as [
              keyof typeof FORMAT_PRICING,
              (typeof FORMAT_PRICING)[keyof typeof FORMAT_PRICING],
            ][]
          ).map(([key, format]) => (
            <div key={key} className="p-4 bg-surface border border-border rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <h4 className="font-theme-data text-text uppercase text-sm">{key}</h4>
                <span className="text-[var(--accent)] font-theme-data">{format.multiplier}x</span>
              </div>
              <p className="text-text font-medium mb-1">{format.name}</p>
              <p className="text-xs text-text-muted">{format.description}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Cost Calculator */}
      <div className="bg-surface border border-border rounded-lg p-4">
        <button
          onClick={() => setShowCalculator(!showCalculator)}
          className="flex items-center justify-between w-full"
        >
          <h3 className="text-lg font-theme-data text-text">Cost Calculator</h3>
          <span className="text-text-muted">{showCalculator ? '[-]' : '[+]'}</span>
        </button>

        {showCalculator && (
          <div className="mt-4 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-2">
                  ESTIMATED RECORDS
                </label>
                <input
                  type="number"
                  min={100}
                  max={1000000}
                  step={1000}
                  value={estimateRecords}
                  onChange={(e) => setEstimateRecords(parseInt(e.target.value) || 0)}
                  className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-2">
                  EXPORT FORMAT
                </label>
                <select
                  value={estimateFormat}
                  onChange={(e) => setEstimateFormat(e.target.value as keyof typeof FORMAT_PRICING)}
                  className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
                >
                  {Object.entries(FORMAT_PRICING).map(([key, format]) => (
                    <option key={key} value={key}>
                      {format.name} ({format.multiplier}x)
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Estimate Result */}
            <div className="bg-bg rounded-lg p-4">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-text-muted">Free records</p>
                  <p className="text-[var(--accent)] font-theme-data">
                    {estimatedCost.freeRecords.toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-text-muted">Billable records</p>
                  <p className="text-text font-theme-data">
                    {estimatedCost.billableRecords.toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-text-muted">Format multiplier</p>
                  <p className="text-text font-theme-data">{estimatedCost.formatMultiplier}x</p>
                </div>
                <div>
                  <p className="text-text-muted">Usage cost</p>
                  <p className="text-text font-theme-data">${estimatedCost.baseCost.toFixed(2)}</p>
                </div>
              </div>

              <div className="border-t border-border mt-4 pt-4">
                <div className="flex items-center justify-between">
                  <span className="text-text font-theme-data">Estimated Total</span>
                  <span className="text-2xl font-theme-data text-[var(--accent)]">
                    ${estimatedCost.totalCost.toFixed(2)}
                    <span className="text-sm text-text-muted">/month</span>
                  </span>
                </div>
                {tierInfo.price && (
                  <p className="text-xs text-text-muted mt-1">
                    Includes ${tierInfo.price} base plan fee
                  </p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Volume Discounts */}
      <div className="bg-surface border border-border rounded-lg p-4">
        <h3 className="text-lg font-theme-data text-text mb-4">Volume Discounts</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-text-muted text-left">
              <th className="pb-2 font-theme-data">Records/Month</th>
              <th className="pb-2 font-theme-data">Discount</th>
              <th className="pb-2 font-theme-data">Effective Rate</th>
            </tr>
          </thead>
          <tbody className="text-text">
            <tr className="border-t border-border">
              <td className="py-2">100K - 500K</td>
              <td className="py-2 text-[var(--acid-cyan)]">10% off</td>
              <td className="py-2 font-theme-data">
                ${(tierInfo.pricePerRecord * 0.9).toFixed(5)}
              </td>
            </tr>
            <tr className="border-t border-border">
              <td className="py-2">500K - 1M</td>
              <td className="py-2 text-[var(--acid-cyan)]">20% off</td>
              <td className="py-2 font-theme-data">
                ${(tierInfo.pricePerRecord * 0.8).toFixed(5)}
              </td>
            </tr>
            <tr className="border-t border-border">
              <td className="py-2">1M+</td>
              <td className="py-2 text-[var(--accent)]">30% off</td>
              <td className="py-2 font-theme-data">
                ${(tierInfo.pricePerRecord * 0.7).toFixed(5)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* CTA */}
      <div className="flex gap-4">
        <button className="flex-1 py-3 bg-[var(--accent)] text-bg font-theme-data font-bold rounded hover:bg-[var(--accent)]/80 transition-colors">
          Upgrade Plan
        </button>
        <button className="px-6 py-3 bg-surface border border-border text-text font-theme-data rounded hover:border-[var(--accent)]/50 transition-colors">
          Contact Sales
        </button>
      </div>
    </div>
  );
}

export default TrainingPricingPanel;
