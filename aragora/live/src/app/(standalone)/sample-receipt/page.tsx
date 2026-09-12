'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useTheme } from '@/context/ThemeContext';
import { Header } from '@/components/landing/Header';
import { Footer } from '@/components/landing/Footer';

// Hardcoded sample receipt — same content also served as a static asset at
// /sample-receipt.json so a stranger can `curl` it and verify the hash offline.
const SAMPLE_RECEIPT = {
  receipt_id: 'DR-MOCK-BCDFC27A',
  question: 'Should we adopt microservices or keep our monolith?',
  verdict: 'consensus',
  confidence: 0.74,
  agents: ['Analyst', 'Critic', 'Synthesizer', "Devil's Advocate"],
  rounds: 2,
  summary:
    'Proceed with a phased rollout, explicit success metrics, and a defined rollback trigger before scaling the change.',
  dissent: [] as string[],
  dissenting_views: [] as string[],
  consensus_proof: {
    reached: true,
    method: 'majority',
    confidence: 0.74,
    supporting_agents: ['Analyst', 'Critic', 'Synthesizer', "Devil's Advocate"],
    dissenting_agents: [] as string[],
  },
  artifact_hash: 'bcdfc27a428d4a72294cd4274c31e85f274756ddbc240f7df1e3953cba5f3218',
  signature_algorithm: 'SHA-256-content-hash',
  elapsed_seconds: 0.0,
  mode: 'demo (offline)',
  proposals: {
    Analyst: 'Start with a narrow pilot so you learn before taking on system-wide risk.',
    Critic: 'Avoid a broad rollout until you can quantify operational cost and rollback criteria.',
    Synthesizer:
      'Combine a limited pilot with measurable guardrails and a written review checkpoint.',
    "Devil's Advocate":
      'Assume the first plan is wrong and add a hard stop if evidence turns against it.',
  },
} as const;

const SAMPLE_RECEIPT_JSON = JSON.stringify(SAMPLE_RECEIPT, null, 2);

function CodeBlock({
  children,
  lang,
  small = false,
}: {
  children: string;
  lang?: string;
  small?: boolean;
}) {
  return (
    <div style={{ borderRadius: '10px', overflow: 'hidden', border: '1px solid var(--border)' }}>
      {lang && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '8px 16px',
            backgroundColor: 'var(--surface-elevated)',
            borderBottom: '1px solid var(--border)',
            fontSize: '11px',
            fontFamily: 'var(--font-theme-data, monospace)',
            color: 'var(--text-muted)',
            textTransform: 'uppercase' as const,
            letterSpacing: '0.06em',
          }}
        >
          {lang}
        </div>
      )}
      <pre
        style={{
          margin: 0,
          padding: '16px',
          backgroundColor: 'var(--surface)',
          overflowX: 'auto',
          fontSize: small ? '12px' : '13px',
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          color: 'var(--text)',
          lineHeight: 1.6,
          maxHeight: small ? undefined : '520px',
        }}
      >
        <code>{children}</code>
      </pre>
    </div>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard.writeText(value).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 2000);
        });
      }}
      style={{
        padding: '6px 12px',
        borderRadius: '8px',
        border: '1px solid var(--border)',
        backgroundColor: 'var(--surface-elevated)',
        color: 'var(--text)',
        fontSize: '12px',
        fontFamily: 'var(--font-landing)',
        cursor: 'pointer',
      }}
      aria-live="polite"
    >
      {copied ? 'Copied' : label}
    </button>
  );
}

function FieldRow({ name, what }: { name: string; what: string }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(180px, 220px) 1fr',
        gap: '14px',
        padding: '10px 0',
        borderTop: '1px solid color-mix(in srgb, var(--border) 60%, transparent)',
      }}
    >
      <code
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: '12px',
          color: 'var(--accent)',
          alignSelf: 'start',
        }}
      >
        {name}
      </code>
      <span style={{ color: 'var(--text-muted)', fontSize: '14px', lineHeight: 1.6 }}>{what}</span>
    </div>
  );
}

export default function SampleReceiptPage() {
  const { theme } = useTheme();

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: 'var(--bg)',
        color: 'var(--text)',
        fontFamily: 'var(--font-landing)',
      }}
      data-landing-theme={theme}
    >
      <Header />

      <main style={{ maxWidth: '900px', margin: '0 auto', padding: '56px 24px 80px' }}>
        {/* Title */}
        <div style={{ textAlign: 'center', marginBottom: '40px' }}>
          <h1
            style={{
              fontSize: '36px',
              fontWeight: 700,
              color: 'var(--accent)',
              marginBottom: '10px',
              fontFamily: 'var(--font-landing)',
            }}
          >
            Sample debate receipt
          </h1>
          <p
            style={{
              color: 'var(--text-muted)',
              fontSize: '18px',
              fontFamily: 'var(--font-landing)',
              margin: 0,
            }}
          >
            What every Aragora debate produces — a portable, content-hashed artifact that records
            who deliberated, what they said, how they disagreed, and what was decided.
          </p>
        </div>

        {/* Receipt JSON section */}
        <section
          style={{
            borderRadius: '14px',
            border: '1px solid var(--border)',
            backgroundColor: 'color-mix(in srgb, var(--surface) 40%, transparent)',
            padding: '24px 28px',
            marginBottom: '32px',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '14px',
              flexWrap: 'wrap',
              gap: '10px',
            }}
          >
            <h2
              style={{
                margin: 0,
                fontSize: '20px',
                fontWeight: 600,
                color: 'var(--text)',
                fontFamily: 'var(--font-landing)',
              }}
            >
              The artifact
            </h2>
            <div style={{ display: 'flex', gap: '8px' }}>
              <CopyButton value={SAMPLE_RECEIPT_JSON} label="Copy JSON" />
              <a
                href="/sample-receipt.json"
                download
                style={{
                  padding: '6px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  backgroundColor: 'var(--surface-elevated)',
                  color: 'var(--text)',
                  fontSize: '12px',
                  fontFamily: 'var(--font-landing)',
                  textDecoration: 'none',
                }}
              >
                Download
              </a>
            </div>
          </div>
          <CodeBlock lang="json">{SAMPLE_RECEIPT_JSON}</CodeBlock>
          <p style={{ marginTop: '14px', color: 'var(--text-muted)', fontSize: '13px' }}>
            Also fetchable at{' '}
            <a
              href="/sample-receipt.json"
              style={{ color: 'var(--accent)', textDecoration: 'underline' }}
            >
              /sample-receipt.json
            </a>{' '}
            so you can pipe it through your own tooling without leaving your terminal.
          </p>
        </section>

        {/* Field guide */}
        <section
          style={{
            borderRadius: '14px',
            border: '1px solid var(--border)',
            backgroundColor: 'color-mix(in srgb, var(--surface) 40%, transparent)',
            padding: '24px 28px',
            marginBottom: '32px',
          }}
        >
          <h2
            style={{
              margin: '0 0 16px',
              fontSize: '20px',
              fontWeight: 600,
              color: 'var(--text)',
              fontFamily: 'var(--font-landing)',
            }}
          >
            What each field means
          </h2>
          <FieldRow
            name="receipt_id"
            what="Stable handle for this decision. Reference it in tickets, post-mortems, or downstream automation."
          />
          <FieldRow
            name="question"
            what="Verbatim prompt the agents debated. Bound to the artifact_hash so a strange question can't be quietly substituted later."
          />
          <FieldRow
            name="agents"
            what="The heterogeneous panel that deliberated. In production this is models from different vendors so they don't share blind spots."
          />
          <FieldRow
            name="proposals"
            what="Each agent's individual position, captured before consensus. The dissent surface — not collapsed into a single answer."
          />
          <FieldRow
            name="verdict"
            what={`"consensus" if a majority converged; "no_consensus" if the panel couldn't agree. The receipt records the disagreement either way.`}
          />
          <FieldRow
            name="confidence"
            what="Convergence strength — how strongly the panel agreed, not just whether they agreed. Use it as a calibration signal, not a probability."
          />
          <FieldRow
            name="consensus_proof"
            what="Method (majority / unanimity / weighted), the agents who supported, and the agents who dissented. Audit trail for how this verdict was reached."
          />
          <FieldRow
            name="artifact_hash"
            what="SHA-256 over the canonical receipt body. Recompute it yourself to confirm nothing changed between when the decision was made and when you read it."
          />
          <FieldRow
            name="signature_algorithm"
            what="The hash construction. Production receipts add an HMAC layer keyed by ARAGORA_CONTEXT_SIGNING_KEY for tamper-evidence."
          />
          <FieldRow
            name="mode"
            what="How the receipt was produced. Demo receipts are flagged so they can't accidentally be promoted to production audit evidence."
          />
        </section>

        {/* Verify yourself */}
        <section
          style={{
            borderRadius: '14px',
            border: '1px solid var(--border)',
            backgroundColor: 'color-mix(in srgb, var(--surface) 40%, transparent)',
            padding: '24px 28px',
            marginBottom: '32px',
          }}
        >
          <h2
            style={{
              margin: '0 0 12px',
              fontSize: '20px',
              fontWeight: 600,
              color: 'var(--text)',
              fontFamily: 'var(--font-landing)',
            }}
          >
            Verify the hash yourself
          </h2>
          <p style={{ marginTop: 0, color: 'var(--text-muted)', fontSize: '14px' }}>
            The whole point of a content-hashed receipt is that you don&apos;t have to trust us.
            Fetch the JSON, hash it the same way, compare to the value claimed inside.
          </p>
          <CodeBlock lang="bash" small>{`# Fetch the artifact and recompute the hash over its body
curl -s https://aragora.ai/sample-receipt.json \\
  | jq 'del(.artifact_hash, .signature_algorithm)' \\
  | python3 -c "import sys,hashlib,json; \\
      body = json.dumps(json.load(sys.stdin), sort_keys=True, separators=(',', ':')); \\
      print(hashlib.sha256(body.encode()).hexdigest())"`}</CodeBlock>
          <p style={{ marginTop: '12px', color: 'var(--text-muted)', fontSize: '13px' }}>
            For production receipts, this is one half of the verification — the other half is the
            HMAC, keyed by your workspace&apos;s signing key, which lets you detect tampering by
            anyone who didn&apos;t have the key.
          </p>
        </section>

        {/* Why this matters */}
        <section
          style={{
            borderRadius: '14px',
            border: '1px solid var(--border)',
            backgroundColor: 'color-mix(in srgb, var(--surface) 40%, transparent)',
            padding: '24px 28px',
            marginBottom: '40px',
          }}
        >
          <h2
            style={{
              margin: '0 0 16px',
              fontSize: '20px',
              fontWeight: 600,
              color: 'var(--text)',
              fontFamily: 'var(--font-landing)',
            }}
          >
            Why this shape
          </h2>
          <ul
            style={{
              margin: 0,
              paddingLeft: '20px',
              color: 'var(--text-muted)',
              fontSize: '14px',
              lineHeight: 1.8,
            }}
          >
            <li>
              <strong style={{ color: 'var(--text)' }}>Dissent is recorded, not collapsed.</strong>{' '}
              You can answer &quot;was there disagreement?&quot; from the receipt itself, weeks or
              months later.
            </li>
            <li>
              <strong style={{ color: 'var(--text)' }}>Portable.</strong> The receipt is a single
              JSON blob. No proprietary format, no required viewer, no signed-URL expiry.
            </li>
            <li>
              <strong style={{ color: 'var(--text)' }}>Verifiable offline.</strong> The
              artifact_hash means a recipient never has to trust the provider — only the math.
            </li>
            <li>
              <strong style={{ color: 'var(--text)' }}>
                Decision-grounded, not just action-logged.
              </strong>{' '}
              The receipt captures the deliberation that led to a decision, not just the executed
              action. The execution gate that consumes it denies anything without an admin-scoped
              approval artifact.
            </li>
          </ul>
        </section>

        {/* CTAs */}
        <div style={{ marginTop: '8px' }}>
          <h2
            style={{
              fontSize: '13px',
              fontWeight: 600,
              color: 'var(--text-muted)',
              textTransform: 'uppercase' as const,
              letterSpacing: '0.06em',
              marginBottom: '16px',
              fontFamily: 'var(--font-landing)',
            }}
          >
            Next
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
            <Link
              href="/try"
              style={{
                padding: '20px',
                borderRadius: '14px',
                border: '1px solid color-mix(in srgb, var(--accent) 25%, transparent)',
                backgroundColor: 'color-mix(in srgb, var(--accent) 5%, transparent)',
                textDecoration: 'none',
                display: 'block',
              }}
            >
              <span
                style={{
                  fontSize: '16px',
                  fontWeight: 600,
                  color: 'var(--accent)',
                  fontFamily: 'var(--font-landing)',
                }}
              >
                Generate one for your own question
              </span>
              <p
                style={{
                  fontSize: '14px',
                  color: 'var(--text-muted)',
                  margin: '6px 0 0',
                  fontFamily: 'var(--font-landing)',
                }}
              >
                No account needed. Runs in your browser.
              </p>
            </Link>
            <Link
              href="/quickstart"
              style={{
                padding: '20px',
                borderRadius: '14px',
                border: '1px solid var(--border)',
                textDecoration: 'none',
                display: 'block',
              }}
            >
              <span
                style={{
                  fontSize: '16px',
                  fontWeight: 600,
                  color: 'var(--text)',
                  fontFamily: 'var(--font-landing)',
                }}
              >
                Run it locally
              </span>
              <p
                style={{
                  fontSize: '14px',
                  color: 'var(--text-muted)',
                  margin: '6px 0 0',
                  fontFamily: 'var(--font-landing)',
                }}
              >
                pip install aragora-debate — under a minute to a real receipt.
              </p>
            </Link>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  );
}
