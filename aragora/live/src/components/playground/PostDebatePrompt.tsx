'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PostDebatePromptProps {
  /** The debate ID (for lead capture) */
  debateId: string;
  /** Share URL path from the debate result (e.g. /debates/abc123) */
  shareUrl: string;
  /** Whether the prompt is visible */
  visible: boolean;
}

type Action = 'idle' | 'share-copied' | 'email-form' | 'email-submitted' | 'email-error';

// ---------------------------------------------------------------------------
// PostDebatePrompt
// ---------------------------------------------------------------------------

export function PostDebatePrompt({ debateId, shareUrl, visible }: PostDebatePromptProps) {
  const [dismissed, setDismissed] = useState(false);
  const [action, setAction] = useState<Action>('idle');
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [mounted, setMounted] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Trigger slide-up animation after becoming visible
  useEffect(() => {
    if (visible && !dismissed) {
      // Small delay so the CSS transition can animate from the initial state
      const timer = setTimeout(() => setMounted(true), 50);
      return () => clearTimeout(timer);
    }
    if (!visible) {
      setMounted(false);
    }
  }, [visible, dismissed]);

  // Reset state when a new debate completes
  useEffect(() => {
    if (visible) {
      setDismissed(false);
      setAction('idle');
      setEmail('');
      setSubmitting(false);
    }
  }, [debateId, visible]);

  const handleShare = useCallback(async () => {
    const url = shareUrl
      ? `${window.location.origin}${shareUrl}`
      : `${window.location.origin}/playground`;
    try {
      await navigator.clipboard.writeText(url);
      setAction('share-copied');
      setTimeout(() => {
        setAction((prev) => (prev === 'share-copied' ? 'idle' : prev));
      }, 2500);
    } catch {
      // Fallback: select text in a temporary input (older browsers)
      const input = document.createElement('input');
      input.value = url;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
      setAction('share-copied');
      setTimeout(() => {
        setAction((prev) => (prev === 'share-copied' ? 'idle' : prev));
      }, 2500);
    }
  }, [shareUrl]);

  const handleEmailSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!email.trim() || submitting) return;

      setSubmitting(true);
      try {
        const res = await fetch('/api/v1/leads/capture', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: email.trim(),
            debate_id: debateId,
            source: 'playground_post_debate',
          }),
        });
        if (res.ok) {
          setAction('email-submitted');
        } else {
          setAction('email-error');
        }
      } catch {
        setAction('email-error');
      } finally {
        setSubmitting(false);
      }
    },
    [email, debateId, submitting],
  );

  if (!visible || dismissed) return null;

  return (
    <div
      ref={containerRef}
      style={{
        opacity: mounted ? 1 : 0,
        transform: mounted ? 'translateY(0)' : 'translateY(24px)',
        transition: 'opacity 0.5s ease-out, transform 0.5s ease-out',
        fontFamily: 'var(--font-landing)',
      }}
    >
      <div
        style={{
          position: 'relative',
          maxWidth: '640px',
          margin: '0 auto',
          padding: '32px 28px',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-button)',
          backgroundColor: 'var(--surface, var(--bg))',
        }}
      >
        {/* Dismiss button */}
        <button
          onClick={() => setDismissed(true)}
          aria-label="Dismiss"
          style={{
            position: 'absolute',
            top: '12px',
            right: '12px',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--text-muted)',
            fontSize: '18px',
            lineHeight: 1,
            padding: '4px',
            transition: 'color 0.15s',
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-primary, var(--text))';
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-muted)';
          }}
        >
          &times;
        </button>

        {/* Header */}
        <p
          style={{
            fontFamily: 'var(--font-landing)',
            fontSize: '15px',
            fontWeight: 600,
            color: 'var(--text-primary, var(--text))',
            marginBottom: '4px',
            marginTop: 0,
          }}
        >
          Debate complete.
        </p>
        <p
          style={{
            fontFamily: 'var(--font-landing)',
            fontSize: '13px',
            color: 'var(--text-muted)',
            marginTop: 0,
            marginBottom: '24px',
          }}
        >
          What would you like to do next?
        </p>

        {/* Actions */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {/* 1. Share -- most prominent */}
          <button
            onClick={handleShare}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              padding: '14px 24px',
              fontFamily: 'var(--font-landing)',
              fontSize: '14px',
              fontWeight: 600,
              color: action === 'share-copied' ? 'var(--accent)' : 'var(--bg)',
              backgroundColor:
                action === 'share-copied' ? 'transparent' : 'var(--accent)',
              border:
                action === 'share-copied'
                  ? '1px solid var(--accent)'
                  : '1px solid var(--accent)',
              borderRadius: 'var(--radius-button)',
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            {action === 'share-copied' ? (
              <>
                <CheckIcon />
                Link copied
              </>
            ) : (
              <>
                <ShareIcon />
                Share this debate
              </>
            )}
          </button>

          {/* 2. Save for later (email capture) */}
          {action !== 'email-submitted' ? (
            action === 'email-form' || action === 'email-error' ? (
              <form
                onSubmit={handleEmailSubmit}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                }}
              >
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com"
                    required
                    autoFocus
                    style={{
                      flex: 1,
                      padding: '10px 14px',
                      fontFamily: 'var(--font-landing)',
                      fontSize: '13px',
                      color: 'var(--text-primary, var(--text))',
                      backgroundColor: 'var(--bg)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-button)',
                      outline: 'none',
                    }}
                    onFocus={(e) => {
                      e.currentTarget.style.borderColor = 'var(--accent)';
                    }}
                    onBlur={(e) => {
                      e.currentTarget.style.borderColor = 'var(--border)';
                    }}
                  />
                  <button
                    type="submit"
                    disabled={submitting || !email.trim()}
                    style={{
                      padding: '10px 20px',
                      fontFamily: 'var(--font-landing)',
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--bg)',
                      backgroundColor: 'var(--accent)',
                      border: '1px solid var(--accent)',
                      borderRadius: 'var(--radius-button)',
                      cursor: submitting ? 'wait' : 'pointer',
                      opacity: submitting || !email.trim() ? 0.5 : 1,
                      transition: 'opacity 0.15s',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {submitting ? 'Sending...' : 'Send'}
                  </button>
                </div>
                {action === 'email-error' && (
                  <p
                    style={{
                      fontFamily: 'var(--font-landing)',
                      fontSize: '12px',
                      color: 'var(--crimson, #ef4444)',
                      margin: 0,
                    }}
                  >
                    Could not save. Please try again.
                  </p>
                )}
              </form>
            ) : (
              <button
                onClick={() => setAction('email-form')}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  padding: '12px 24px',
                  fontFamily: 'var(--font-landing)',
                  fontSize: '13px',
                  fontWeight: 500,
                  color: 'var(--text-muted)',
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-button)',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--accent)';
                  e.currentTarget.style.color = 'var(--text-primary, var(--text))';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--border)';
                  e.currentTarget.style.color = 'var(--text-muted)';
                }}
              >
                <BookmarkIcon />
                Save for later
              </button>
            )
          ) : (
            <p
              style={{
                fontFamily: 'var(--font-landing)',
                fontSize: '13px',
                color: 'var(--accent)',
                textAlign: 'center',
                margin: '4px 0',
              }}
            >
              Saved. We will send you a link shortly.
            </p>
          )}

          {/* 3. Create free account */}
          <Link
            href="/signup"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              padding: '12px 24px',
              fontFamily: 'var(--font-landing)',
              fontSize: '13px',
              fontWeight: 500,
              color: 'var(--text-muted)',
              backgroundColor: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-button)',
              textDecoration: 'none',
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--accent)';
              e.currentTarget.style.color = 'var(--text-primary, var(--text))';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--border)';
              e.currentTarget.style.color = 'var(--text-muted)';
            }}
          >
            <UserPlusIcon />
            Create free account
          </Link>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline SVG icons (keeps the component self-contained, no external deps)
// ---------------------------------------------------------------------------

function ShareIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
      <polyline points="16 6 12 2 8 6" />
      <line x1="12" y1="2" x2="12" y2="15" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function BookmarkIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function UserPlusIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="8.5" cy="7" r="4" />
      <line x1="20" y1="8" x2="20" y2="14" />
      <line x1="23" y1="11" x2="17" y2="11" />
    </svg>
  );
}
