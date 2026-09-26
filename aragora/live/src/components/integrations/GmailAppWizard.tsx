'use client';

import { useState, useEffect, useCallback } from 'react';

interface GmailAccount {
  email: string;
  connected_at: string;
  is_active: boolean;
  scopes: string[];
}

interface GmailLabel {
  id: string;
  name: string;
  type: 'system' | 'user';
}

interface GmailAppWizardProps {
  onClose: () => void;
  onComplete: () => void;
  apiBaseUrl?: string;
}

type WizardStep = 'check' | 'authorize' | 'scopes' | 'labels' | 'test' | 'complete';

const AVAILABLE_SCOPES = [
  {
    key: 'gmail.readonly',
    label: 'Read emails',
    description: 'Read email messages and metadata',
    required: true,
  },
  {
    key: 'gmail.send',
    label: 'Send emails',
    description: 'Send debate results and notifications via email',
    required: false,
  },
  {
    key: 'gmail.labels',
    label: 'Manage labels',
    description: 'Create and apply labels to organize debate-related emails',
    required: false,
  },
];

export function GmailAppWizard({ onClose, onComplete, apiBaseUrl = '' }: GmailAppWizardProps) {
  const [step, setStep] = useState<WizardStep>('check');
  const [error, setError] = useState<string | null>(null);
  const [isConfigured, setIsConfigured] = useState<boolean | null>(null);
  const [account, setAccount] = useState<GmailAccount | null>(null);
  const [labels, setLabels] = useState<GmailLabel[]>([]);
  const [selectedScopes, setSelectedScopes] = useState<string[]>(['gmail.readonly']);
  const [selectedLabels, setSelectedLabels] = useState<string[]>([]);
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'failed'>('idle');
  const [loading, setLoading] = useState(false);

  // Check if Gmail OAuth is configured
  const checkConfiguration = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/gmail/status`);
      if (!response.ok) {
        setIsConfigured(false);
        return;
      }
      const data = await response.json();
      setIsConfigured(data.oauth_configured ?? false);

      if (data.account) {
        setAccount(data.account);
        setStep('labels');
      } else if (data.oauth_configured) {
        setStep('scopes');
      }
    } catch {
      setIsConfigured(false);
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    if (step === 'check') {
      checkConfiguration();
    }
  }, [step, checkConfiguration]);

  // Load available labels
  const loadLabels = useCallback(async () => {
    if (!account) return;

    setLoading(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/gmail/labels`);
      if (response.ok) {
        const data = await response.json();
        setLabels(data.labels || []);
      }
    } catch {
      setLabels([]);
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, account]);

  useEffect(() => {
    if (step === 'labels' && account) {
      loadLabels();
    }
  }, [step, account, loadLabels]);

  // Handle OAuth callback
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.type === 'gmail-oauth-complete') {
        setAccount(event.data.account);
        setStep('labels');
      } else if (event.data?.type === 'gmail-oauth-error') {
        setError(event.data.error || 'OAuth flow failed');
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  const startOAuth = () => {
    const scopeParam = selectedScopes.join(',');
    const width = 500;
    const height = 600;
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;

    const popup = window.open(
      `${apiBaseUrl}/api/integrations/gmail/authorize?scopes=${encodeURIComponent(scopeParam)}`,
      'gmail-oauth',
      `width=${width},height=${height},left=${left},top=${top},popup=yes`,
    );

    if (!popup) {
      setError('Popup blocked. Please allow popups and try again.');
    }
  };

  const handleScopeToggle = (scope: string) => {
    const scopeConfig = AVAILABLE_SCOPES.find((s) => s.key === scope);
    if (scopeConfig?.required) return;

    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  };

  const handleLabelToggle = (labelId: string) => {
    setSelectedLabels((prev) =>
      prev.includes(labelId) ? prev.filter((id) => id !== labelId) : [...prev, labelId],
    );
  };

  const saveLabelConfig = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/gmail/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ labels: selectedLabels }),
      });

      if (!response.ok) {
        throw new Error('Failed to save label configuration');
      }

      setStep('test');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save configuration');
    } finally {
      setLoading(false);
    }
  };

  const testConnection = async () => {
    setTestStatus('testing');
    setError(null);

    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/gmail/test`, { method: 'POST' });

      if (!response.ok) {
        throw new Error('Test failed');
      }

      setTestStatus('success');
      setTimeout(() => setStep('complete'), 1500);
    } catch (err) {
      setTestStatus('failed');
      setError(err instanceof Error ? err.message : 'Test failed');
    }
  };

  const renderStep = () => {
    switch (step) {
      case 'check':
        return (
          <div className="text-center py-8">
            {loading ? (
              <>
                <div className="animate-pulse font-theme-data text-[var(--acid-cyan)] mb-4">
                  [CHECKING CONFIGURATION...]
                </div>
                <p className="font-theme-data text-sm text-text-muted">
                  Verifying Google OAuth is configured
                </p>
              </>
            ) : isConfigured === false ? (
              <>
                <div className="font-theme-data text-warning text-4xl mb-4">!</div>
                <h3 className="font-theme-data text-lg text-text mb-2">
                  Gmail OAuth Not Configured
                </h3>
                <p className="font-theme-data text-sm text-text-muted mb-4">
                  The server needs Google Cloud credentials to enable Gmail integration.
                </p>
                <div className="bg-bg/50 border border-[var(--accent)]/20 p-4 rounded text-left">
                  <p className="font-theme-data text-xs text-text-muted mb-2">
                    1. Create a project in{' '}
                    <a
                      href="https://console.cloud.google.com/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[var(--acid-cyan)] hover:underline"
                    >
                      Google Cloud Console
                    </a>
                  </p>
                  <p className="font-theme-data text-xs text-text-muted mb-2">
                    2. Enable the Gmail API and create OAuth credentials
                  </p>
                  <p className="font-theme-data text-xs text-text-muted mb-2">
                    3. Add the following environment variables:
                  </p>
                  <pre className="font-theme-data text-xs text-[var(--accent)] bg-bg p-2 rounded overflow-x-auto">
                    {`GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=https://your-domain/api/integrations/gmail/callback`}
                  </pre>
                </div>
              </>
            ) : (
              <div className="font-theme-data text-[var(--accent)]">
                Configuration verified. Proceeding to scope selection...
              </div>
            )}
          </div>
        );

      case 'scopes':
        return (
          <div className="py-4">
            <h3 className="font-theme-data text-lg text-text mb-2">Select Permissions</h3>
            <p className="font-theme-data text-sm text-text-muted mb-4">
              Choose which Gmail permissions Aragora should request:
            </p>

            <div className="space-y-3">
              {AVAILABLE_SCOPES.map((scope) => (
                <label
                  key={scope.key}
                  className={`flex items-start gap-3 p-3 border rounded transition-colors ${
                    scope.required
                      ? 'border-[var(--accent)]/50 bg-[var(--accent)]/5 cursor-not-allowed'
                      : selectedScopes.includes(scope.key)
                        ? 'border-[var(--accent)] bg-[var(--accent)]/10 cursor-pointer'
                        : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40 cursor-pointer'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedScopes.includes(scope.key)}
                    onChange={() => handleScopeToggle(scope.key)}
                    disabled={scope.required}
                    className="form-checkbox bg-bg border-[var(--accent)]/30 mt-0.5"
                  />
                  <div>
                    <span className="font-theme-data text-sm text-text block">
                      {scope.label}
                      {scope.required && (
                        <span className="text-[var(--accent)]/70 ml-2">(required)</span>
                      )}
                    </span>
                    <span className="font-theme-data text-xs text-text-muted">
                      {scope.description}
                    </span>
                  </div>
                </label>
              ))}
            </div>
          </div>
        );

      case 'authorize':
        return (
          <div className="text-center py-8">
            <div className="font-theme-data text-[var(--acid-cyan)] text-4xl mb-4">@</div>
            <h3 className="font-theme-data text-lg text-text mb-2">Authorize Gmail Access</h3>
            <p className="font-theme-data text-sm text-text-muted mb-6">
              Click the button below to sign in with your Google account and grant Aragora access to
              your Gmail.
            </p>
            <button
              onClick={startOAuth}
              className="px-6 py-3 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors"
            >
              [SIGN IN WITH GOOGLE]
            </button>
          </div>
        );

      case 'labels':
        return (
          <div className="py-4">
            <div className="mb-4">
              {account && (
                <div className="flex items-center gap-2 mb-4 p-3 bg-[var(--accent)]/10 border border-[var(--accent)]/30 rounded">
                  <span className="font-theme-data text-[var(--accent)]">Connected:</span>
                  <span className="font-theme-data text-text">{account.email}</span>
                </div>
              )}
              <h3 className="font-theme-data text-lg text-text mb-2">Select Labels (Optional)</h3>
              <p className="font-theme-data text-sm text-text-muted">
                Choose labels to filter or organize debate-related emails:
              </p>
            </div>

            {loading ? (
              <div className="text-center py-8 font-theme-data text-[var(--acid-cyan)]">
                [LOADING LABELS...]
              </div>
            ) : labels.length === 0 ? (
              <div className="text-center py-8">
                <p className="font-theme-data text-sm text-text-muted mb-4">
                  No custom labels found. You can create labels later.
                </p>
                <button
                  onClick={() => setStep('test')}
                  className="px-4 py-2 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/10"
                >
                  [SKIP - CONFIGURE LATER]
                </button>
              </div>
            ) : (
              <div className="space-y-2 max-h-60 overflow-y-auto">
                {labels
                  .filter((l) => l.type === 'user')
                  .map((label) => (
                    <label
                      key={label.id}
                      className={`flex items-center gap-3 p-3 border rounded cursor-pointer transition-colors ${
                        selectedLabels.includes(label.id)
                          ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                          : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedLabels.includes(label.id)}
                        onChange={() => handleLabelToggle(label.id)}
                        className="form-checkbox bg-bg border-[var(--accent)]/30"
                      />
                      <span className="font-theme-data text-sm text-text">{label.name}</span>
                    </label>
                  ))}
              </div>
            )}
          </div>
        );

      case 'test':
        return (
          <div className="text-center py-8">
            <h3 className="font-theme-data text-lg text-text mb-2">Test Connection</h3>
            <p className="font-theme-data text-sm text-text-muted mb-6">
              Verify the Gmail integration by fetching account info.
            </p>

            <button
              onClick={testConnection}
              disabled={testStatus === 'testing'}
              className={`px-6 py-3 font-theme-data text-sm border transition-colors ${
                testStatus === 'success'
                  ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                  : testStatus === 'failed'
                    ? 'bg-warning/20 border-warning text-warning'
                    : 'bg-[var(--acid-cyan)]/20 border-[var(--acid-cyan)] text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/30'
              }`}
            >
              {testStatus === 'testing' && '[TESTING CONNECTION...]'}
              {testStatus === 'success' && '[CONNECTION VERIFIED!]'}
              {testStatus === 'failed' && '[TEST FAILED - TRY AGAIN]'}
              {testStatus === 'idle' && '[TEST CONNECTION]'}
            </button>

            {testStatus === 'success' && (
              <p className="font-theme-data text-sm text-[var(--accent)] mt-4">
                Gmail integration is working correctly!
              </p>
            )}
          </div>
        );

      case 'complete':
        return (
          <div className="text-center py-8">
            <div className="font-theme-data text-[var(--accent)] text-4xl mb-4">✓</div>
            <h3 className="font-theme-data text-lg text-text mb-2">Gmail Integration Complete!</h3>
            <p className="font-theme-data text-sm text-text-muted mb-6">
              Aragora can now {selectedScopes.includes('gmail.send') ? 'send and ' : ''}
              read emails from your Gmail account.
            </p>
          </div>
        );
    }
  };

  const canGoBack = !['check', 'complete'].includes(step);
  const canGoNext =
    (step === 'scopes' && selectedScopes.length > 0) ||
    (step === 'labels' && true) ||
    (step === 'test' && testStatus === 'success');

  const handleBack = () => {
    if (step === 'scopes') setStep('check');
    else if (step === 'authorize') setStep('scopes');
    else if (step === 'labels') setStep('authorize');
    else if (step === 'test') setStep('labels');
  };

  const handleNext = () => {
    if (step === 'scopes') {
      setStep('authorize');
    } else if (step === 'labels') {
      if (selectedLabels.length > 0) {
        saveLabelConfig();
      } else {
        setStep('test');
      }
    } else if (step === 'test' && testStatus === 'success') {
      setStep('complete');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-surface border border-[var(--accent)]/30 rounded-lg w-full max-w-xl max-h-[90vh] overflow-hidden">
        <div className="p-4 border-b border-[var(--accent)]/20 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="font-theme-data text-[var(--acid-cyan)] text-xl">@</span>
            <div>
              <h2 className="font-theme-data text-[var(--accent)] text-lg">Gmail Setup</h2>
              <p className="font-theme-data text-xs text-text-muted">
                Connect Aragora to your Gmail account
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text font-theme-data">
            [X]
          </button>
        </div>

        <div className="p-6">
          {error && (
            <div className="mb-4 p-3 border border-warning/30 bg-warning/10 rounded">
              <p className="text-warning font-theme-data text-sm">{error}</p>
            </div>
          )}

          {renderStep()}
        </div>

        <div className="p-4 border-t border-[var(--accent)]/20 flex justify-between">
          {canGoBack ? (
            <button
              onClick={handleBack}
              className="px-4 py-2 border border-[var(--accent)]/30 text-text-muted font-theme-data text-sm hover:text-text transition-colors"
            >
              [BACK]
            </button>
          ) : (
            <button
              onClick={onClose}
              className="px-4 py-2 border border-[var(--accent)]/30 text-text-muted font-theme-data text-sm hover:text-text transition-colors"
            >
              [CANCEL]
            </button>
          )}

          {step === 'complete' ? (
            <button
              onClick={onComplete}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors"
            >
              [DONE]
            </button>
          ) : step === 'authorize' ? (
            <button
              onClick={startOAuth}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors"
            >
              [SIGN IN WITH GOOGLE]
            </button>
          ) : canGoNext ? (
            <button
              onClick={handleNext}
              disabled={loading}
              className="px-4 py-2 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/10 transition-colors disabled:opacity-50"
            >
              {loading ? '[SAVING...]' : '[NEXT]'}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default GmailAppWizard;
