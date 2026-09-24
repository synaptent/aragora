'use client';

import { useState, useEffect, useCallback } from 'react';

interface TeamsWorkspace {
  tenant_id: string;
  tenant_name: string;
  connected_at: string;
  is_active: boolean;
}

interface TeamsChannel {
  id: string;
  name: string;
  team_name: string;
}

interface TeamsAppWizardProps {
  onClose: () => void;
  onComplete: () => void;
  apiBaseUrl?: string;
}

type WizardStep = 'check' | 'consent' | 'channels' | 'test' | 'complete';

export function TeamsAppWizard({ onClose, onComplete, apiBaseUrl = '' }: TeamsAppWizardProps) {
  const [step, setStep] = useState<WizardStep>('check');
  const [error, setError] = useState<string | null>(null);
  const [isConfigured, setIsConfigured] = useState<boolean | null>(null);
  const [workspace, setWorkspace] = useState<TeamsWorkspace | null>(null);
  const [channels, setChannels] = useState<TeamsChannel[]>([]);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'failed'>('idle');
  const [loading, setLoading] = useState(false);
  const [consentUrl, setConsentUrl] = useState<string | null>(null);

  // Check if Teams OAuth is configured on the server
  const checkConfiguration = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/teams/status`);
      if (!response.ok) {
        setIsConfigured(false);
        return;
      }
      const data = await response.json();
      setIsConfigured(data.oauth_configured ?? false);
      setConsentUrl(data.consent_url ?? null);

      if (data.workspace) {
        setWorkspace(data.workspace);
        setStep('channels');
      } else if (data.oauth_configured) {
        setStep('consent');
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

  // Load available channels after workspace is connected
  const loadChannels = useCallback(async () => {
    if (!workspace) return;

    setLoading(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/teams/channels`);
      if (response.ok) {
        const data = await response.json();
        setChannels(data.channels || []);
      }
    } catch {
      setChannels([]);
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, workspace]);

  useEffect(() => {
    if (step === 'channels' && workspace) {
      loadChannels();
    }
  }, [step, workspace, loadChannels]);

  // Handle OAuth callback
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.type === 'teams-oauth-complete') {
        setWorkspace(event.data.workspace);
        setStep('channels');
      } else if (event.data?.type === 'teams-oauth-error') {
        setError(event.data.error || 'OAuth flow failed');
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  const startAdminConsent = () => {
    if (!consentUrl) {
      setError('Admin consent URL not available');
      return;
    }

    const width = 600;
    const height = 700;
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;

    const popup = window.open(
      consentUrl,
      'teams-oauth',
      `width=${width},height=${height},left=${left},top=${top},popup=yes`,
    );

    if (!popup) {
      setError('Popup blocked. Please allow popups and try again.');
    }
  };

  const handleChannelToggle = (channelId: string) => {
    setSelectedChannels((prev) =>
      prev.includes(channelId) ? prev.filter((id) => id !== channelId) : [...prev, channelId],
    );
  };

  const saveChannelConfig = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/teams/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channels: selectedChannels }),
      });

      if (!response.ok) {
        throw new Error('Failed to save channel configuration');
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
      const response = await fetch(`${apiBaseUrl}/api/integrations/teams/test`, { method: 'POST' });

      if (!response.ok) {
        throw new Error('Test message failed');
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
                  Verifying Microsoft Teams OAuth is configured
                </p>
              </>
            ) : isConfigured === false ? (
              <>
                <div className="font-theme-data text-warning text-4xl mb-4">!</div>
                <h3 className="font-theme-data text-lg text-text mb-2">
                  Teams OAuth Not Configured
                </h3>
                <p className="font-theme-data text-sm text-text-muted mb-4">
                  The server needs Microsoft Entra ID app credentials.
                </p>
                <div className="bg-bg/50 border border-[var(--accent)]/20 p-4 rounded text-left">
                  <p className="font-theme-data text-xs text-text-muted mb-2">
                    1. Register an app in{' '}
                    <a
                      href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[var(--acid-cyan)] hover:underline"
                    >
                      Azure Portal
                    </a>
                  </p>
                  <p className="font-theme-data text-xs text-text-muted mb-2">
                    2. Add the following environment variables:
                  </p>
                  <pre className="font-theme-data text-xs text-[var(--accent)] bg-bg p-2 rounded overflow-x-auto">
                    {`TEAMS_APP_ID=your_application_id
TEAMS_APP_PASSWORD=your_client_secret
TEAMS_TENANT_ID=your_tenant_id`}
                  </pre>
                  <p className="font-theme-data text-xs text-text-muted mt-2">
                    3. Configure API permissions: ChannelMessage.Send, Team.ReadBasic.All
                  </p>
                </div>
              </>
            ) : (
              <div className="font-theme-data text-[var(--accent)]">
                Configuration verified. Proceeding to admin consent...
              </div>
            )}
          </div>
        );

      case 'consent':
        return (
          <div className="text-center py-8">
            <div className="font-theme-data text-[var(--acid-cyan)] text-4xl mb-4">T#</div>
            <h3 className="font-theme-data text-lg text-text mb-2">Admin Consent Required</h3>
            <p className="font-theme-data text-sm text-text-muted mb-6">
              A Microsoft 365 admin must grant consent for Aragora to access your organization.
              Click the button below to start the consent flow.
            </p>
            <button
              onClick={startAdminConsent}
              className="px-6 py-3 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors"
            >
              [START ADMIN CONSENT]
            </button>
            <p className="font-theme-data text-xs text-text-muted mt-4">
              Required permissions: Send channel messages, Read team info
            </p>
          </div>
        );

      case 'channels':
        return (
          <div className="py-4">
            <div className="mb-4">
              {workspace && (
                <div className="flex items-center gap-2 mb-4 p-3 bg-[var(--accent)]/10 border border-[var(--accent)]/30 rounded">
                  <span className="font-theme-data text-[var(--accent)]">Connected to:</span>
                  <span className="font-theme-data text-text">{workspace.tenant_name}</span>
                </div>
              )}
              <h3 className="font-theme-data text-lg text-text mb-2">Select Channels</h3>
              <p className="font-theme-data text-sm text-text-muted">
                Choose which Teams channels should receive debate notifications:
              </p>
            </div>

            {loading ? (
              <div className="text-center py-8 font-theme-data text-[var(--acid-cyan)]">
                [LOADING CHANNELS...]
              </div>
            ) : channels.length === 0 ? (
              <div className="text-center py-8">
                <p className="font-theme-data text-sm text-text-muted mb-4">
                  No channels found. The app may need to be added to teams first.
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
                {channels.map((channel) => (
                  <label
                    key={channel.id}
                    className={`flex items-center gap-3 p-3 border rounded cursor-pointer transition-colors ${
                      selectedChannels.includes(channel.id)
                        ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                        : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedChannels.includes(channel.id)}
                      onChange={() => handleChannelToggle(channel.id)}
                      className="form-checkbox bg-bg border-[var(--accent)]/30"
                    />
                    <div>
                      <span className="font-theme-data text-sm text-text block">
                        {channel.name}
                      </span>
                      <span className="font-theme-data text-xs text-text-muted">
                        {channel.team_name}
                      </span>
                    </div>
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
              Send a test Adaptive Card to verify the integration is working.
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
              {testStatus === 'testing' && '[SENDING TEST CARD...]'}
              {testStatus === 'success' && '[TEST SUCCESSFUL!]'}
              {testStatus === 'failed' && '[TEST FAILED - TRY AGAIN]'}
              {testStatus === 'idle' && '[SEND TEST CARD]'}
            </button>

            {testStatus === 'success' && (
              <p className="font-theme-data text-sm text-[var(--accent)] mt-4">
                Check your Teams channel for the test Adaptive Card!
              </p>
            )}
          </div>
        );

      case 'complete':
        return (
          <div className="text-center py-8">
            <div className="font-theme-data text-[var(--accent)] text-4xl mb-4">✓</div>
            <h3 className="font-theme-data text-lg text-text mb-2">Teams Integration Complete!</h3>
            <p className="font-theme-data text-sm text-text-muted mb-6">
              Aragora is now connected to Microsoft Teams. Debate results will be posted as Adaptive
              Cards to your selected channels.
            </p>
          </div>
        );
    }
  };

  const canGoBack = step !== 'check' && step !== 'complete';
  const canGoNext =
    (step === 'channels' && (selectedChannels.length > 0 || channels.length === 0)) ||
    (step === 'test' && testStatus === 'success');

  const handleBack = () => {
    if (step === 'consent') setStep('check');
    else if (step === 'channels') setStep('consent');
    else if (step === 'test') setStep('channels');
  };

  const handleNext = () => {
    if (step === 'channels') {
      if (selectedChannels.length > 0) {
        saveChannelConfig();
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
            <span className="font-theme-data text-[var(--acid-cyan)] text-xl">T#</span>
            <div>
              <h2 className="font-theme-data text-[var(--accent)] text-lg">
                Microsoft Teams Setup
              </h2>
              <p className="font-theme-data text-xs text-text-muted">
                Connect Aragora to your Microsoft 365 organization
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

export default TeamsAppWizard;
