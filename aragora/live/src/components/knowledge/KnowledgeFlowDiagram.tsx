'use client';

import { useKnowledgeFlow } from '@/hooks/useKnowledgeFlow';
import { useMemo } from 'react';

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n) + '...' : s;
}

export function KnowledgeFlowDiagram() {
  const { flows, stats, loading, error } = useKnowledgeFlow();

  const {
    sourceDebates,
    kmNodes,
    targetDebates,
    links: _links,
  } = useMemo(() => {
    const sources = new Map<string, { id: string; label: string; count: number }>();
    const targets = new Map<string, { id: string; label: string; count: number }>();
    const nodes = new Map<string, { id: string; label: string; delta: number }>();
    const linkList: Array<{ from: string; to: string; value: number; color: string }> = [];

    for (const f of flows) {
      const sid = f.source_debate_id;
      if (!sources.has(sid)) sources.set(sid, { id: sid, label: truncate(sid, 12), count: 0 });
      sources.get(sid)!.count++;

      const nid = f.km_node_id;
      if (!nodes.has(nid))
        nodes.set(nid, { id: nid, label: truncate(f.content_preview || nid, 20), delta: 0 });
      nodes.get(nid)!.delta += f.confidence_delta;

      linkList.push({
        from: sid,
        to: nid,
        value: Math.abs(f.confidence_delta),
        color: f.confidence_delta >= 0 ? '#34d399' : '#f87171',
      });

      if (f.target_debate_id) {
        const tid = f.target_debate_id;
        if (!targets.has(tid)) targets.set(tid, { id: tid, label: truncate(tid, 12), count: 0 });
        targets.get(tid)!.count++;
        linkList.push({ from: nid, to: tid, value: 0.5, color: '#60a5fa' });
      }
    }

    return {
      sourceDebates: Array.from(sources.values()),
      kmNodes: Array.from(nodes.values()),
      targetDebates: Array.from(targets.values()),
      links: linkList,
    };
  }, [flows]);

  if (loading)
    return (
      <div className="animate-pulse p-4 text-[var(--text-muted)] font-theme-data">
        Loading knowledge flow...
      </div>
    );
  if (error)
    return <div className="p-4 text-red-400 font-theme-data">Failed to load flow data</div>;

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      <div className="flex gap-6 font-theme-data text-xs text-[var(--text-muted)]">
        <span>
          Flows: <span className="text-[var(--acid-green)]">{stats.total_flows}</span>
        </span>
        <span>
          Avg Confidence &Delta;:{' '}
          <span className="text-[var(--acid-green)]">{stats.avg_confidence_change.toFixed(3)}</span>
        </span>
        <span>
          Debates Enriched:{' '}
          <span className="text-[var(--acid-green)]">{stats.debates_enriched}</span>
        </span>
      </div>

      {flows.length === 0 ? (
        <div className="text-[var(--text-muted)] font-theme-data text-sm p-4">
          No knowledge flow data yet. Run debates with{' '}
          <code className="text-[var(--acid-green)]">enable_knowledge_injection=True</code> to
          generate flow data.
        </div>
      ) : (
        <div className="card p-4 overflow-x-auto">
          <div className="grid grid-cols-3 gap-8 min-w-[600px]">
            {/* Source Debates */}
            <div className="space-y-2">
              <h4 className="font-theme-data text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
                Source Debates
              </h4>
              {sourceDebates.map((d) => (
                <div key={d.id} className="card p-2 border-l-2 border-emerald-400">
                  <span className="font-theme-data text-xs text-[var(--text)]">{d.label}</span>
                  <span className="block text-[10px] font-theme-data text-[var(--text-muted)]">
                    {d.count} contributions
                  </span>
                </div>
              ))}
            </div>

            {/* KM Nodes */}
            <div className="space-y-2">
              <h4 className="font-theme-data text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
                Knowledge Nodes
              </h4>
              {kmNodes.map((n) => (
                <div
                  key={n.id}
                  className={`card p-2 border-l-2 ${n.delta >= 0 ? 'border-emerald-400' : 'border-red-400'}`}
                >
                  <span className="font-theme-data text-xs text-[var(--text)]">{n.label}</span>
                  <span
                    className={`block text-[10px] font-theme-data ${n.delta >= 0 ? 'text-emerald-400' : 'text-red-400'}`}
                  >
                    &Delta; {n.delta >= 0 ? '+' : ''}
                    {n.delta.toFixed(3)}
                  </span>
                </div>
              ))}
            </div>

            {/* Target Debates */}
            <div className="space-y-2">
              <h4 className="font-theme-data text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
                Enriched Debates
              </h4>
              {targetDebates.map((d) => (
                <div key={d.id} className="card p-2 border-l-2 border-blue-400">
                  <span className="font-theme-data text-xs text-[var(--text)]">{d.label}</span>
                  <span className="block text-[10px] font-theme-data text-[var(--text-muted)]">
                    {d.count} injections
                  </span>
                </div>
              ))}
              {targetDebates.length === 0 && (
                <p className="text-[var(--text-muted)] font-theme-data text-[10px]">
                  No target debates yet
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
