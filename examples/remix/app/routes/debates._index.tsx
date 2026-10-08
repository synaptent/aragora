import type { MetaFunction } from '@remix-run/node';
import { json } from '@remix-run/node';
import { Link, useLoaderData } from '@remix-run/react';
import { getClient } from '../aragora.server';
import { debateView } from '../debate-view';

export const meta: MetaFunction = () => [{ title: 'Debates | Aragora' }];

export async function loader() {
  const client = getClient();

  try {
    const response = await client.debates.list({ limit: 20 });
    return json({ debates: response.debates || [] });
  } catch (error) {
    console.error('Failed to fetch debates:', error);
    return json({ debates: [] });
  }
}

export default function DebatesIndex() {
  const { debates } = useLoaderData<typeof loader>();

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <h1>Debates</h1>
        <Link to="/debates/new" className="button">
          New Debate
        </Link>
      </div>

      {debates.length === 0 ? (
        <div className="card">
          <p style={{ color: 'var(--text-muted)' }}>
            No debates yet. Create your first debate to get started.
          </p>
        </div>
      ) : (
        <div className="grid">
          {debates.map(debate => (
            <Link
              key={debate.debate_id}
              to={`/debates/${debate.debate_id}`}
              style={{ textDecoration: 'none', color: 'inherit' }}
            >
              <div className="card" style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <span className={`status-badge status-${debate.status}`} style={{ padding: '0.25rem 0.75rem', borderRadius: '9999px', fontSize: '0.875rem' }}>
                    {debate.status}
                  </span>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
                    {new Date(debate.created_at).toLocaleDateString()}
                  </span>
                </div>
                <h3 style={{ marginBottom: '0.5rem' }}>
                  {debate.task?.slice(0, 60) || 'Untitled Debate'}
                  {debate.task?.length > 60 ? '...' : ''}
                </h3>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
                  {debate.agents?.length || 0} agents | {debateView(debate).roundsCompleted} {debateView(debate).roundsCompleted === 1 ? 'round' : 'rounds'} completed
                </p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
