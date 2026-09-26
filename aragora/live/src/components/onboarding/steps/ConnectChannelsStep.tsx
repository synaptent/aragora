'use client';

import { useState } from 'react';
import { useOnboardingStore } from '@/store/onboardingStore';

interface ChannelOption {
  id: string;
  name: string;
  icon: string;
  description: string;
}

const CHANNELS: ChannelOption[] = [
  {
    id: 'slack',
    name: 'Slack',
    icon: 'S',
    description: 'Get debate results and notifications in Slack channels',
  },
  {
    id: 'teams',
    name: 'Microsoft Teams',
    icon: 'T',
    description: 'Deliver decision receipts to Teams conversations',
  },
  {
    id: 'email',
    name: 'Email',
    icon: 'E',
    description: 'Receive debate summaries and receipts via email',
  },
];

export function ConnectChannelsStep() {
  const [selectedChannels, setSelectedChannels] = useState<Set<string>>(new Set());
  const updateChecklist = useOnboardingStore((s) => s.updateChecklist);

  const toggleChannel = (id: string) => {
    setSelectedChannels((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      if (next.size > 0) {
        updateChecklist({ channelConnected: true });
      }
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-theme-data text-[var(--acid-green)] mb-2">Connect Channels</h2>
        <p className="text-sm font-theme-data text-[var(--text-muted)]">
          Optional: deliver debate results to your team&apos;s existing tools. You can set this up
          later in Settings.
        </p>
      </div>

      <div className="space-y-3">
        {CHANNELS.map((channel) => {
          const isSelected = selectedChannels.has(channel.id);
          return (
            <button
              key={channel.id}
              onClick={() => toggleChannel(channel.id)}
              className={`w-full text-left p-4 border transition-colors flex items-center gap-4 ${
                isSelected
                  ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10'
                  : 'border-[var(--border)] bg-[var(--surface)] hover:border-[var(--acid-green)]/50'
              }`}
            >
              <span
                className={`w-10 h-10 flex items-center justify-center text-sm font-theme-data font-bold shrink-0 ${
                  isSelected
                    ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)]'
                    : 'bg-[var(--border)] text-[var(--text-muted)]'
                }`}
              >
                {channel.icon}
              </span>
              <div className="flex-1 min-w-0">
                <div
                  className={`text-sm font-theme-data font-bold ${
                    isSelected ? 'text-[var(--acid-green)]' : 'text-[var(--text)]'
                  }`}
                >
                  {channel.name}
                </div>
                <p className="text-xs font-theme-data text-[var(--text-muted)]">
                  {channel.description}
                </p>
              </div>
              <span
                className={`text-xs font-theme-data px-2 py-0.5 ${
                  isSelected
                    ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)]'
                    : 'bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)]'
                }`}
              >
                {isSelected ? 'SELECTED' : 'ADD'}
              </span>
            </button>
          );
        })}
      </div>

      {selectedChannels.size > 0 && (
        <div className="p-3 border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/5 text-xs font-theme-data text-[var(--acid-green)]">
          {'>'} {selectedChannels.size} channel{selectedChannels.size > 1 ? 's' : ''} selected. You
          can configure credentials in Settings after onboarding.
        </div>
      )}

      {selectedChannels.size === 0 && (
        <div className="p-3 border border-[var(--border)] bg-[var(--surface)] text-xs font-theme-data text-[var(--text-muted)]">
          No channels selected. You can always connect channels later from Settings.
        </div>
      )}
    </div>
  );
}
