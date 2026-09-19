import { Suspense } from 'react';
import { getServerClient } from '@/lib/aragora';
import { debateView } from '@/lib/debate-view';
import DebateStream from './DebateStream';

interface PageProps {
  params: Promise<{ id: string }>;
}

// Fetch initial debate data on server
async function getDebate(id: string) {
  const client = getServerClient();
  try {
    return await client.debates.get(id);
  } catch (error) {
    console.error('Failed to fetch debate:', error);
    return null;
  }
}

export default async function DebateDetailPage({ params }: PageProps) {
  const { id } = await params;
  const debate = await getDebate(id);

  if (!debate) {
    return (
      <div className="card">
        <h2>Debate not found</h2>
        <p style={{ color: 'var(--text-muted)' }}>
          The debate with ID &quot;{id}&quot; could not be found.
        </p>
      </div>
    );
  }

  const view = debateView(debate);

  return (
    <div>
      <div style={{ marginBottom: '2rem' }}>
        <span className={`status-badge status-${debate.status}`}>
          {debate.status}
        </span>
        <h1 style={{ marginTop: '1rem' }}>{debate.task}</h1>
        <p style={{ color: 'var(--text-muted)' }}>
          Created {new Date(debate.created_at).toLocaleString()}
        </p>
      </div>

      <div className="grid" style={{ marginBottom: '2rem' }}>
        <div className="card">
          <h3>Agents</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
            {(debate.agents || []).map((agent: string) => (
              <span
                key={agent}
                style={{
                  padding: '0.25rem 0.75rem',
                  background: 'var(--bg)',
                  borderRadius: '9999px',
                  fontSize: '0.875rem',
                }}
              >
                {agent}
              </span>
            ))}
          </div>
        </div>

        <div className="card">
          <h3>Rounds Completed</h3>
          <p style={{ marginTop: '0.5rem' }}>
            {view.roundsCompleted}
          </p>
        </div>
      </div>

      {/* Real-time stream for running debates */}
      {debate.status === 'running' && (
        <div className="card">
          <h3 style={{ marginBottom: '1rem' }}>Live Stream</h3>
          <Suspense fallback={<div>Connecting to stream...</div>}>
            <DebateStream key={id} debateId={id} />
          </Suspense>
        </div>
      )}

      {/* Consensus result for completed debates */}
      {debate.status === 'completed' && debate.consensus && (
        <div className="card" style={{ borderColor: 'var(--primary)' }}>
          <h3 style={{ color: 'var(--primary)', marginBottom: '1rem' }}>
            {debate.consensus.reached ? 'Consensus Reached' : 'No Consensus'}
          </h3>
          {view.answer && <p style={{ marginBottom: '1rem' }}>{view.answer}</p>}
          <div style={{ display: 'flex', gap: '2rem' }}>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Confidence</span>
              <p style={{ fontSize: '1.25rem', fontWeight: 600 }}>
                {view.confidence}
              </p>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Agreement</span>
              <p style={{ fontSize: '1.25rem', fontWeight: 600 }}>
                {view.agreement}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Messages history */}
      {view.messages.length > 0 && (
        <div className="card">
          <h3 style={{ marginBottom: '1rem' }}>Debate History</h3>
          <div style={{ maxHeight: '500px', overflowY: 'auto' }}>
            {view.messages.map((msg, idx) => (
              <div
                key={idx}
                style={{
                  padding: '1rem',
                  borderBottom: '1px solid var(--border)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <strong>{msg.agent ?? msg.agent_id ?? msg.role}</strong>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
                    Round {msg.round}
                  </span>
                </div>
                <p style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
