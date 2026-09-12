'use client';

import { useState, useEffect, useCallback } from 'react';

interface SlackWorkspace {
  id: string;
  name: string;
  connected_at: string;
  is_active: boolean;
}

interface SlackChannel {
  id: string;
  name: string;
  is_private: boolean;
  is_member: boolean;
}

interface SlackAppWizardProps {
  onClose: () => void;
  onComplete: () => void;
  apiBaseUrl?: string;
}

type WizardStep = 'check' | 'install' | 'channels' | 'test' | 'complete';

export function SlackAppWizard({ onClose, onComplete, apiBaseUrl = '' }: SlackAppWizardProps) {
  const [step, setStep] = useState<WizardStep>('check');
  const [error, setError] = useState<string | null>(null);
  const [isConfigured, setIsConfigured] = useState<boolean | null>(null);
  const [workspace, setWorkspace] = useState<SlackWorkspace | null>(null);
  const [channels, setChannels] = useState<SlackChannel[]>([]);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'failed'>('idle');
  const [loading, setLoading] = useState(false);

  // Check if Slack OAuth is configured on the server
  const checkConfiguration = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/slack/status`);
      if (!response.ok) {
        // If endpoint doesn't exist, assume not configured
        setIsConfigured(false);
        return;
      }
      const data = await response.json();
      setIsConfigured(data.oauth_configured ?? false);

      // If a workspace is already connected, load it
      if (data.workspace) {
        setWorkspace(data.workspace);
        setStep('channels');
      } else if (data.oauth_configured) {
        setStep('install');
      }
    } catch {
      // Network error - assume configuration check endpoint not available
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
      const response = await fetch(`${apiBaseUrl}/api/integrations/slack/channels`);
      if (response.ok) {
        const data = await response.json();
        setChannels(data.channels || []);
      }
    } catch {
      // Channels API may not be available
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

  // Handle OAuth callback (via message from popup window)
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.type === 'slack-oauth-complete') {
        setWorkspace(event.data.workspace);
        setStep('channels');
      } else if (event.data?.type === 'slack-oauth-error') {
        setError(event.data.error || 'OAuth flow failed');
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  const startOAuth = () => {
    // Open OAuth flow in popup window
    const width = 600;
    const height = 700;
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;

    const popup = window.open(
      `${apiBaseUrl}/api/integrations/slack/install?host=${encodeURIComponent(window.location.host)}`,
      'slack-oauth',
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
      const response = await fetch(`${apiBaseUrl}/api/integrations/slack/config`, {
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
      const response = await fetch(`${apiBaseUrl}/api/integrations/slack/test`, { method: 'POST' });

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
                  Verifying Slack OAuth is configured on the server
                </p>
              </>
            ) : isConfigured === false ? (
              <>
                <div className="font-theme-data text-warning text-4xl mb-4">!</div>
                <h3 className="font-theme-data text-lg text-text mb-2">
                  Slack OAuth Not Configured
                </h3>
                <p className="font-theme-data text-sm text-text-muted mb-4">
                  The server needs SLACK_CLIENT_ID and SLACK_CLIENT_SECRET environment variables to
                  enable app installation.
                </p>
                <div className="bg-bg/50 border border-[var(--accent)]/20 p-4 rounded text-left">
                  <p className="font-theme-data text-xs text-text-muted mb-2">
                    1. Create a Slack app at{' '}
                    <a
                      href="https://api.slack.com/apps"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[var(--acid-cyan)] hover:underline"
                    >
                      api.slack.com/apps
                    </a>
                  </p>
                  <p className="font-theme-data text-xs text-text-muted mb-2">
                    2. Add the following environment variables:
                  </p>
                  <pre className="font-theme-data text-xs text-[var(--accent)] bg-bg p-2 rounded overflow-x-auto">
                    {`SLACK_CLIENT_ID=your_client_id
SLACK_CLIENT_SECRET=your_client_secret
SLACK_REDIRECT_URI=https://your-domain/api/integrations/slack/callback`}
                  </pre>
                  <p className="font-theme-data text-xs text-text-muted mt-2">
                    3. Restart the server and try again
                  </p>
                </div>
              </>
            ) : (
              <div className="font-theme-data text-[var(--accent)]">
                Configuration verified. Proceeding to installation...
              </div>
            )}
          </div>
        );

      case 'install':
        return (
          <div className="text-center py-8">
            <div className="font-theme-data text-[var(--acid-cyan)] text-4xl mb-4">#</div>
            <h3 className="font-theme-data text-lg text-text mb-2">Install Aragora Slack App</h3>
            <p className="font-theme-data text-sm text-text-muted mb-6">
              Click the button below to authorize Aragora in your Slack workspace. You&apos;ll be
              redirected to Slack to approve the installation.
            </p>
            <button
              onClick={startOAuth}
              className="px-6 py-3 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors"
            >
              [ADD TO SLACK]
            </button>
            <p className="font-theme-data text-xs text-text-muted mt-4">
              Required permissions: channels:history, chat:write, commands, users:read
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
                  <span className="font-theme-data text-text">{workspace.name}</span>
                </div>
              )}
              <h3 className="font-theme-data text-lg text-text mb-2">Select Channels</h3>
              <p className="font-theme-data text-sm text-text-muted">
                Choose which channels should receive debate notifications:
              </p>
            </div>

            {loading ? (
              <div className="text-center py-8 font-theme-data text-[var(--acid-cyan)]">
                [LOADING CHANNELS...]
              </div>
            ) : channels.length === 0 ? (
              <div className="text-center py-8">
                <p className="font-theme-data text-sm text-text-muted mb-4">
                  No channels found. The bot may need to be invited to channels first.
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
                    <span className="font-theme-data text-sm text-text">
                      {channel.is_private ? '🔒 ' : '#'}
                      {channel.name}
                    </span>
                    {!channel.is_member && (
                      <span className="font-theme-data text-xs text-warning ml-auto">
                        (invite bot first)
                      </span>
                    )}
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
              Send a test message to verify the integration is working.
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
              {testStatus === 'testing' && '[SENDING TEST MESSAGE...]'}
              {testStatus === 'success' && '[TEST SUCCESSFUL!]'}
              {testStatus === 'failed' && '[TEST FAILED - TRY AGAIN]'}
              {testStatus === 'idle' && '[SEND TEST MESSAGE]'}
            </button>

            {testStatus === 'success' && (
              <p className="font-theme-data text-sm text-[var(--accent)] mt-4">
                Check your Slack workspace for the test message!
              </p>
            )}
          </div>
        );

      case 'complete':
        return (
          <div className="text-center py-8">
            <div className="font-theme-data text-[var(--accent)] text-4xl mb-4">✓</div>
            <h3 className="font-theme-data text-lg text-text mb-2">Slack Integration Complete!</h3>
            <p className="font-theme-data text-sm text-text-muted mb-6">
              Aragora is now connected to your Slack workspace. Debate results and notifications
              will be posted to your selected channels.
            </p>
            <div className="space-y-2">
              <p className="font-theme-data text-xs text-text-muted">
                You can manage this integration from the Connectors page.
              </p>
            </div>
          </div>
        );
    }
  };

  const canGoBack = step !== 'check' && step !== 'complete';
  const canGoNext =
    (step === 'channels' && (selectedChannels.length > 0 || channels.length === 0)) ||
    (step === 'test' && testStatus === 'success');

  const handleBack = () => {
    if (step === 'install') setStep('check');
    else if (step === 'channels') setStep('install');
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
      {/* Backdrop */}
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-surface border border-[var(--accent)]/30 rounded-lg w-full max-w-xl max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="p-4 border-b border-[var(--accent)]/20 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="font-theme-data text-[var(--acid-cyan)] text-xl">#</span>
            <div>
              <h2 className="font-theme-data text-[var(--accent)] text-lg">Slack App Setup</h2>
              <p className="font-theme-data text-xs text-text-muted">
                Connect Aragora to your Slack workspace
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text font-theme-data">
            [X]
          </button>
        </div>

        {/* Content */}
        <div className="p-6">
          {error && (
            <div className="mb-4 p-3 border border-warning/30 bg-warning/10 rounded">
              <p className="text-warning font-theme-data text-sm">{error}</p>
            </div>
          )}

          {renderStep()}
        </div>

        {/* Footer */}
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

export default SlackAppWizard;
