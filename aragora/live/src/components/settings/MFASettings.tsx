'use client';

import { useState, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';

interface User {
  mfa_enabled?: boolean;
  email: string;
}

interface MFASettingsProps {
  user: User;
  onMFAStatusChange?: (enabled: boolean) => void;
}

type MFAStep = 'idle' | 'setup' | 'verify' | 'backup' | 'disable';

export function MFASettings({ user, onMFAStatusChange }: MFASettingsProps) {
  const { config } = useBackend();
  const [step, setStep] = useState<MFAStep>('idle');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Setup state
  const [secret, setSecret] = useState<string | null>(null);
  const [provisioningUri, setProvisioningUri] = useState<string | null>(null);
  const [verificationCode, setVerificationCode] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);

  // Disable state
  const [disableCode, setDisableCode] = useState('');
  const [disablePassword, setDisablePassword] = useState('');

  // Regenerate backup codes state
  const [regenerateCode, setRegenerateCode] = useState('');
  const [showRegenerate, setShowRegenerate] = useState(false);

  const mfaEnabled = user.mfa_enabled ?? false;

  // Start MFA setup
  const handleStartSetup = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${config.api}/api/auth/mfa/setup`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to start MFA setup');
      }

      const data = await response.json();
      setSecret(data.secret);
      setProvisioningUri(data.provisioning_uri);
      setStep('setup');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start MFA setup');
    } finally {
      setLoading(false);
    }
  }, [config.api]);

  // Verify and enable MFA
  const handleVerifyAndEnable = useCallback(async () => {
    if (verificationCode.length !== 6) {
      setError('Please enter a 6-digit code');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${config.api}/api/auth/mfa/enable`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: verificationCode }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Invalid verification code');
      }

      const data = await response.json();
      setBackupCodes(data.backup_codes || []);
      setStep('backup');
      onMFAStatusChange?.(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification failed');
    } finally {
      setLoading(false);
    }
  }, [config.api, verificationCode, onMFAStatusChange]);

  // Disable MFA
  const handleDisable = useCallback(async () => {
    if (!disableCode && !disablePassword) {
      setError('Please enter your MFA code or password');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${config.api}/api/auth/mfa/disable`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: disableCode || undefined,
          password: disablePassword || undefined,
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to disable MFA');
      }

      setStep('idle');
      setDisableCode('');
      setDisablePassword('');
      onMFAStatusChange?.(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to disable MFA');
    } finally {
      setLoading(false);
    }
  }, [config.api, disableCode, disablePassword, onMFAStatusChange]);

  // Regenerate backup codes
  const handleRegenerateBackupCodes = useCallback(async () => {
    if (regenerateCode.length !== 6) {
      setError('Please enter a 6-digit code');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${config.api}/api/auth/mfa/backup-codes`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: regenerateCode }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to regenerate backup codes');
      }

      const data = await response.json();
      setBackupCodes(data.backup_codes || []);
      setStep('backup');
      setRegenerateCode('');
      setShowRegenerate(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to regenerate backup codes');
    } finally {
      setLoading(false);
    }
  }, [config.api, regenerateCode]);

  const resetState = useCallback(() => {
    setStep('idle');
    setError(null);
    setSecret(null);
    setProvisioningUri(null);
    setVerificationCode('');
    setBackupCodes([]);
    setDisableCode('');
    setDisablePassword('');
    setRegenerateCode('');
    setShowRegenerate(false);
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="font-theme-data text-sm text-text">Two-Factor Authentication (2FA)</h4>
          <p className="font-theme-data text-xs text-text-muted mt-1">
            Add an extra layer of security to your account using an authenticator app.
          </p>
        </div>
        <div
          className={`px-2 py-1 rounded text-xs font-theme-data ${
            mfaEnabled ? 'bg-[var(--accent)]/20 text-[var(--accent)]' : 'bg-surface text-text-muted'
          }`}
        >
          {mfaEnabled ? 'ENABLED' : 'DISABLED'}
        </div>
      </div>

      {error && (
        <div className="p-3 bg-acid-red/10 border border-acid-red/30 rounded">
          <p className="font-theme-data text-xs text-acid-red">{error}</p>
        </div>
      )}

      {/* Idle state - show enable/disable button */}
      {step === 'idle' && (
        <div className="space-y-3">
          {!mfaEnabled ? (
            <button
              onClick={handleStartSetup}
              disabled={loading}
              className="w-full px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Setting up...' : 'Enable 2FA'}
            </button>
          ) : (
            <>
              <button
                onClick={() => setShowRegenerate(!showRegenerate)}
                className="w-full px-4 py-2 border border-[var(--acid-cyan)]/40 text-[var(--acid-cyan)] font-theme-data text-sm rounded hover:bg-[var(--acid-cyan)]/10 transition-colors"
              >
                {showRegenerate ? 'Cancel' : 'Regenerate Backup Codes'}
              </button>

              {showRegenerate && (
                <div className="p-4 bg-surface rounded border border-[var(--acid-cyan)]/30 space-y-3">
                  <p className="font-theme-data text-xs text-text-muted">
                    Enter your current 2FA code to generate new backup codes. Old backup codes will
                    be invalidated.
                  </p>
                  <input
                    type="text"
                    value={regenerateCode}
                    onChange={(e) =>
                      setRegenerateCode(e.target.value.replace(/\D/g, '').slice(0, 6))
                    }
                    placeholder="6-digit code"
                    className="w-full bg-bg border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm text-center tracking-widest focus:outline-none focus:border-[var(--accent)]"
                    maxLength={6}
                  />
                  <button
                    onClick={handleRegenerateBackupCodes}
                    disabled={loading || regenerateCode.length !== 6}
                    className="w-full px-4 py-2 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)]/40 text-[var(--acid-cyan)] font-theme-data text-sm rounded hover:bg-[var(--acid-cyan)]/30 transition-colors disabled:opacity-50"
                  >
                    {loading ? 'Generating...' : 'Generate New Codes'}
                  </button>
                </div>
              )}

              <button
                onClick={() => setStep('disable')}
                className="w-full px-4 py-2 border border-acid-red/40 text-acid-red font-theme-data text-sm rounded hover:bg-acid-red/10 transition-colors"
              >
                Disable 2FA
              </button>
            </>
          )}
        </div>
      )}

      {/* Setup step - show QR code and secret */}
      {step === 'setup' && (
        <div className="space-y-4 p-4 bg-surface rounded border border-[var(--accent)]/30">
          <h5 className="font-theme-data text-sm text-[var(--accent)]">Step 1: Scan QR Code</h5>
          <p className="font-theme-data text-xs text-text-muted">
            Scan this QR code with your authenticator app (Google Authenticator, Authy, 1Password,
            etc.)
          </p>

          {provisioningUri && (
            <div className="flex justify-center p-4 bg-white rounded">
              {/* QR Code placeholder - in production, use a QR code library */}
              <div className="w-48 h-48 flex items-center justify-center border-2 border-dashed border-gray-300 rounded">
                <div className="text-center text-gray-500 text-xs p-2">
                  <p className="mb-2">Scan with authenticator app:</p>
                  <code className="block text-[10px] break-all">{provisioningUri}</code>
                </div>
              </div>
            </div>
          )}

          <div className="space-y-2">
            <p className="font-theme-data text-xs text-text-muted">
              Or manually enter this secret key:
            </p>
            <div className="flex gap-2">
              <code className="flex-1 bg-bg p-2 rounded font-theme-data text-sm text-text text-center tracking-wider">
                {secret}
              </code>
              <button
                onClick={() => navigator.clipboard.writeText(secret || '')}
                className="px-3 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-xs rounded hover:bg-[var(--accent)]/30"
              >
                Copy
              </button>
            </div>
          </div>

          <h5 className="font-theme-data text-sm text-[var(--accent)] mt-6">Step 2: Verify Code</h5>
          <p className="font-theme-data text-xs text-text-muted">
            Enter the 6-digit code from your authenticator app to complete setup.
          </p>

          <input
            type="text"
            value={verificationCode}
            onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
            className="w-full bg-bg border border-[var(--accent)]/30 rounded px-3 py-3 font-theme-data text-lg text-center tracking-[0.5em] focus:outline-none focus:border-[var(--accent)]"
            maxLength={6}
            autoComplete="one-time-code"
          />

          <div className="flex gap-2">
            <button
              onClick={resetState}
              className="flex-1 px-4 py-2 border border-[var(--accent)]/40 text-text-muted font-theme-data text-sm rounded hover:text-text transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleVerifyAndEnable}
              disabled={loading || verificationCode.length !== 6}
              className="flex-1 px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Verifying...' : 'Enable 2FA'}
            </button>
          </div>
        </div>
      )}

      {/* Backup codes step */}
      {step === 'backup' && (
        <div className="space-y-4 p-4 bg-surface rounded border border-acid-yellow/30">
          <div className="flex items-start gap-2">
            <span className="text-[var(--acid-yellow)]">!</span>
            <div>
              <h5 className="font-theme-data text-sm text-[var(--acid-yellow)]">
                Save Your Backup Codes
              </h5>
              <p className="font-theme-data text-xs text-text-muted mt-1">
                These codes can be used to access your account if you lose your authenticator. Each
                code can only be used once. Store them securely.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 p-3 bg-bg rounded">
            {backupCodes.map((code, i) => (
              <code key={i} className="font-theme-data text-sm text-text text-center py-1">
                {code}
              </code>
            ))}
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => {
                const text = backupCodes.join('\n');
                navigator.clipboard.writeText(text);
              }}
              className="flex-1 px-4 py-2 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/10 transition-colors"
            >
              Copy Codes
            </button>
            <button
              onClick={() => {
                const text = `Aragora 2FA Backup Codes\n${user.email}\n${'='.repeat(30)}\n\n${backupCodes.join('\n')}\n\nKeep these codes safe!`;
                const blob = new Blob([text], { type: 'text/plain' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'aragora-backup-codes.txt';
                a.click();
                URL.revokeObjectURL(url);
              }}
              className="flex-1 px-4 py-2 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/10 transition-colors"
            >
              Download
            </button>
          </div>

          <button
            onClick={resetState}
            className="w-full px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors"
          >
            I&apos;ve Saved My Codes
          </button>
        </div>
      )}

      {/* Disable step */}
      {step === 'disable' && (
        <div className="space-y-4 p-4 bg-surface rounded border border-acid-red/30">
          <h5 className="font-theme-data text-sm text-acid-red">
            Disable Two-Factor Authentication
          </h5>
          <p className="font-theme-data text-xs text-text-muted">
            Enter your current 2FA code OR your account password to disable 2FA.
          </p>

          <div className="space-y-3">
            <div>
              <label className="font-theme-data text-xs text-text-muted block mb-1">2FA Code</label>
              <input
                type="text"
                value={disableCode}
                onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="6-digit code"
                className="w-full bg-bg border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm text-center tracking-widest focus:outline-none focus:border-[var(--accent)]"
                maxLength={6}
              />
            </div>

            <div className="flex items-center gap-4">
              <div className="flex-1 h-px bg-[var(--accent)]/20" />
              <span className="font-theme-data text-xs text-text-muted">OR</span>
              <div className="flex-1 h-px bg-[var(--accent)]/20" />
            </div>

            <div>
              <label className="font-theme-data text-xs text-text-muted block mb-1">Password</label>
              <input
                type="password"
                value={disablePassword}
                onChange={(e) => setDisablePassword(e.target.value)}
                placeholder="Your account password"
                className="w-full bg-bg border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={resetState}
              className="flex-1 px-4 py-2 border border-[var(--accent)]/40 text-text-muted font-theme-data text-sm rounded hover:text-text transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleDisable}
              disabled={loading || (!disableCode && !disablePassword)}
              className="flex-1 px-4 py-2 bg-acid-red/20 border border-acid-red/40 text-acid-red font-theme-data text-sm rounded hover:bg-acid-red/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Disabling...' : 'Disable 2FA'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default MFASettings;
