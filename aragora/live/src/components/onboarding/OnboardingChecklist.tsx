'use client';

import { useOnboardingStore } from '@/store/onboardingStore';
import { useAuth } from '@/context/AuthContext';
import type { OnboardingChecklist as ChecklistType } from '@/store/onboardingStore';

interface ChecklistItem {
  key: keyof ChecklistType;
  label: string;
}

const CHECKLIST_ITEMS: ChecklistItem[] = [
  { key: 'accountCreated', label: 'Account created' },
  { key: 'firstDebateRun', label: 'First debate run' },
  { key: 'teamMemberInvited', label: 'Team member invited' },
  { key: 'channelConnected', label: 'Channel connected' },
];

export function OnboardingChecklist() {
  const checklist = useOnboardingStore((s) => s.checklist);
  const { isAuthenticated } = useAuth();

  // Derive accountCreated from auth state
  const derivedChecklist = {
    ...checklist,
    accountCreated: isAuthenticated || checklist.accountCreated,
  };

  const completedCount = CHECKLIST_ITEMS.filter((item) => derivedChecklist[item.key]).length;
  const totalCount = CHECKLIST_ITEMS.length;
  const percentage = Math.round((completedCount / totalCount) * 100);

  return (
    <div className="border border-[var(--acid-green)]/20 bg-[var(--surface)] p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-theme-data font-bold text-[var(--acid-green)]">
          ONBOARDING CHECKLIST
        </h3>
        <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
          {completedCount}/{totalCount} ({percentage}%)
        </span>
      </div>

      {/* Progress bar */}
      <div className="w-full h-1 bg-[var(--acid-green)]/20 rounded-full overflow-hidden mb-3">
        <div
          className="h-full bg-[var(--acid-green)] transition-all duration-500 ease-out"
          style={{ width: `${percentage}%` }}
        />
      </div>

      {/* Items */}
      <div className="space-y-2">
        {CHECKLIST_ITEMS.map((item) => {
          const isComplete = derivedChecklist[item.key];
          return (
            <div key={item.key} className="flex items-center gap-2 text-sm font-theme-data">
              <span
                className={isComplete ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'}
              >
                {isComplete ? '[x]' : '[ ]'}
              </span>
              <span
                className={
                  isComplete ? 'text-[var(--text)] line-through opacity-60' : 'text-[var(--text)]'
                }
              >
                {item.label}
              </span>
            </div>
          );
        })}
      </div>

      {completedCount === totalCount && (
        <div className="mt-3 p-2 border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/5 text-xs font-theme-data text-[var(--acid-green)] text-center">
          All steps complete. You are ready to go.
        </div>
      )}
    </div>
  );
}
