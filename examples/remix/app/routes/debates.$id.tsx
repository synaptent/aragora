import type { LoaderFunctionArgs, MetaFunction } from '@remix-run/node';
import { json } from '@remix-run/node';
import { useLoaderData } from '@remix-run/react';
import { getClient } from '../aragora.server';
import { DebateStream } from '../DebateStream';
import { debateView } from '../debate-view';

export const meta: MetaFunction<typeof loader> = ({ data }) => [
  { title: data?.debate ? `${data.debate.task} | Aragora` : 'Debate | Aragora' },
];

export async function loader({ params }: LoaderFunctionArgs) {
  const client = getClient();
  try {
    const debate = await client.debates.get(params.id!);
    return json({ debate });
  } catch {
    throw new Response('Debate not found', { status: 404 });
  }
}

export default function DebateDetailPage() {
  const { debate } = useLoaderData<typeof loader>();
  const view = debateView(debate);

  return (
    <div>
      <header style={{ marginBottom: '2rem' }}>
        <span className={`status-badge status-${debate.status}`}>{debate.status}</span>
        <h1 style={{ marginTop: '1rem' }}>{debate.task}</h1>
        <p style={{ color: 'var(--text-muted)' }}>
          Created {new Date(debate.created_at).toLocaleString()}
        </p>
      </header>

      <div className="grid" style={{ marginBottom: '2rem' }}>
        <section>
          <h2>Agents</h2>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
            {debate.agents.map(agent => <span className="agent-tag" key={agent}>{agent}</span>)}
          </div>
        </section>
        <section>
          <h2>Progress</h2>
          <p>{view.roundsCompleted} {view.roundsCompleted === 1 ? 'round' : 'rounds'} completed</p>
        </section>
      </div>

      {debate.status === 'running' && (
        <section className="detail-section">
          <h2>Live Stream</h2>
          <DebateStream key={debate.debate_id} debateId={debate.debate_id} />
        </section>
      )}

      {debate.status === 'completed' && (debate.consensus || view.answer) && (
        <section className="detail-section">
          <h2>{debate.consensus ? (debate.consensus.reached ? 'Consensus Reached' : 'No Consensus') : 'Final Answer'}</h2>
          {view.answer && <p style={{ marginBottom: '1rem' }}>{view.answer}</p>}
          <dl style={{ display: 'flex', flexWrap: 'wrap', gap: '2rem' }}>
            <div><dt>Confidence</dt><dd>{view.confidence}</dd></div>
            <div><dt>Agreement</dt><dd>{view.agreement}</dd></div>
          </dl>
        </section>
      )}

      {view.messages.length > 0 && (
        <section className="detail-section">
          <h2>Debate History</h2>
          <div style={{ maxHeight: '500px', overflowY: 'auto' }}>
            {view.messages.map((message, index) => (
              <div key={index} style={{ padding: '1rem 0', borderBottom: '1px solid var(--border)' }}>
                <div className="event-heading">
                  <strong>{message.agent ?? message.agent_id ?? message.role}</strong>
                  <span style={{ color: 'var(--text-muted)' }}>Round {message.round}</span>
                </div>
                <p style={{ whiteSpace: 'pre-wrap' }}>{message.content}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
