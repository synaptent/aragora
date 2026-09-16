import Link from 'next/link';
import { getServerClient } from '@/lib/aragora';
import { debateView } from '@/lib/debate-view';

export const dynamic = 'force-dynamic';

// Fetch debates on the server
async function getDebates() {
  const client = getServerClient();
  try {
    const response = await client.debates.list({ limit: 20 });
    return response.debates || [];
  } catch (error) {
    console.error('Failed to fetch debates:', error);
    return [];
  }
}

export default async function DebatesPage() {
  const debates = await getDebates();

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <h1>Debates</h1>
        <Link href="/debates/new" className="button">
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
              href={`/debates/${debate.debate_id}`}
              style={{ textDecoration: 'none', color: 'inherit' }}
            >
              <div className="card" style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <span className={`status-badge status-${debate.status}`}>
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
                  {debate.agents?.length || 0} agents | {debateView(debate).roundsCompleted} rounds completed
                </p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
