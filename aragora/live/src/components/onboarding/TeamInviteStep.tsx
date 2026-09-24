'use client';

import { useState } from 'react';
import { useOnboardingStore } from '@/store';

export function TeamInviteStep() {
  const [email, setEmail] = useState('');
  const [emailError, setEmailError] = useState('');

  const { teamMembers, addTeamMember, removeTeamMember } = useOnboardingStore();

  const validateEmail = (email: string) => {
    const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return regex.test(email);
  };

  const handleAddMember = () => {
    if (!email) {
      setEmailError('Email is required');
      return;
    }
    if (!validateEmail(email)) {
      setEmailError('Please enter a valid email');
      return;
    }
    if (teamMembers.some((m) => m.email === email)) {
      setEmailError('This email has already been added');
      return;
    }

    addTeamMember(email);
    setEmail('');
    setEmailError('');
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddMember();
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-theme-data text-[var(--accent)] mb-2">Invite Your Team</h3>
        <p className="text-sm text-text-muted">
          Add team members who will participate in debates (optional)
        </p>
      </div>

      {/* Email Input */}
      <div>
        <label className="block text-sm font-theme-data text-text mb-2">Team Member Email</label>
        <div className="flex gap-2">
          <input
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setEmailError('');
            }}
            onKeyPress={handleKeyPress}
            placeholder="colleague@company.com"
            className="flex-1 px-4 py-2 bg-bg border border-[var(--accent)]/30 rounded text-text font-theme-data focus:border-[var(--accent)] focus:outline-none"
          />
          <button
            onClick={handleAddMember}
            className="px-4 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm hover:bg-[var(--accent)]/90 transition-colors"
          >
            ADD
          </button>
        </div>
        {emailError && <p className="text-xs text-accent-red mt-1">{emailError}</p>}
      </div>

      {/* Team Members List */}
      {teamMembers.length > 0 && (
        <div>
          <label className="block text-sm font-theme-data text-text mb-2">
            Invited Members ({teamMembers.length})
          </label>
          <div className="space-y-2">
            {teamMembers.map((member) => (
              <div
                key={member.email}
                className="flex items-center justify-between px-4 py-2 border border-[var(--accent)]/20 rounded"
              >
                <div>
                  <span className="text-sm text-text font-theme-data">{member.email}</span>
                  <span className="text-xs text-text-muted ml-2">({member.role})</span>
                </div>
                <button
                  onClick={() => removeTeamMember(member.email)}
                  className="text-xs font-theme-data text-text-muted hover:text-accent-red transition-colors"
                >
                  [REMOVE]
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Skip Note */}
      <div className="text-center">
        <p className="text-xs text-text-muted">
          You can skip this step and invite team members later from Settings.
        </p>
      </div>
    </div>
  );
}
