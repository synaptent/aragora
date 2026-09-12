'use client';

import { useState, useTransition } from 'react';

import { apiFetch } from '@/lib/api';

import type { AgentBridgeEvent, AgentBridgeRunDetail } from './types';

interface BridgeOperatorActionsProps {
  run: AgentBridgeRunDetail;
  onDispatched: () => void;
}

function roleOptions(run: AgentBridgeRunDetail): string[] {
  const ordered = run.participants.map((participant) => participant.role);
  const extras = Object.keys(run.roles).filter((role) => !ordered.includes(role));
  return [...ordered, ...extras];
}

export function BridgeOperatorActions({ run, onDispatched }: BridgeOperatorActionsProps) {
  const roles = roleOptions(run);
  const [role, setRole] = useState(run.next_actor ?? roles[0] ?? '');
  const [prompt, setPrompt] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const canAutoStep = run.status === 'running';
  const canManualDispatch = run.status === 'running' || run.status === 'awaiting_human';

  const dispatch = (mode: 'auto-step' | 'dispatch') => {
    setMessage(null);
    startTransition(async () => {
      try {
        if (mode === 'auto-step') {
          const event = await apiFetch<AgentBridgeEvent & { auto_step?: unknown }>(
            `/api/v1/agent-bridge/runs/${encodeURIComponent(run.run_id)}/auto-step`,
            { method: 'POST', body: JSON.stringify({}) },
          );
          setMessage(`Auto-step dispatched ${event.role} turn ${event.turn_index}.`);
        } else {
          const trimmedPrompt = prompt.trim();
          if (!trimmedPrompt) {
            setMessage('Dispatch prompt is required.');
            return;
          }
          const event = await apiFetch<AgentBridgeEvent>(
            `/api/v1/agent-bridge/runs/${encodeURIComponent(run.run_id)}/dispatch`,
            { method: 'POST', body: JSON.stringify({ role, prompt: trimmedPrompt }) },
          );
          setPrompt('');
          setMessage(`Dispatched ${event.role} turn ${event.turn_index}.`);
        }
        onDispatched();
      } catch (error) {
        setMessage(error instanceof Error ? error.message : 'Bridge write request failed.');
      }
    });
  };

  const curl = `curl -X POST "$ARAGORA_API_URL/api/v1/agent-bridge/runs/${run.run_id}/auto-step" \\
  -H "Authorization: Bearer $ARAGORA_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{}'`;

  return (
    <section className="rounded-xl border border-amber-300/20 bg-amber-300/5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-[0.25em] text-amber-200/60">
            Operator actions
          </div>
          <p className="mt-2 max-w-3xl text-sm text-white/60">
            Write actions are owner/admin gated and require ARAGORA_FEATURE_AGENT_BRIDGE_WRITE. Use
            them for bounded handoffs, review loops, and one-step auto-baton validation.
          </p>
        </div>
        <button
          type="button"
          disabled={!canAutoStep || isPending || !run.next_actor}
          onClick={() => dispatch('auto-step')}
          className="rounded border border-amber-200/30 bg-amber-200/10 px-3 py-2 text-sm text-amber-100 transition-colors hover:bg-amber-200/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Auto-step next actor
        </button>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[14rem_1fr_auto]">
        <select
          value={role}
          onChange={(event) => setRole(event.target.value)}
          disabled={!canManualDispatch || isPending}
          className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
        >
          {roles.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <input
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          disabled={!canManualDispatch || isPending}
          placeholder="Manual dispatch prompt"
          className="rounded border border-white/10 bg-black/40 px-3 py-2 text-sm text-white placeholder:text-white/30"
        />
        <button
          type="button"
          disabled={!canManualDispatch || isPending || !role}
          onClick={() => dispatch('dispatch')}
          className="rounded border border-cyan-200/30 bg-cyan-200/10 px-3 py-2 text-sm text-cyan-100 transition-colors hover:bg-cyan-200/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Dispatch turn
        </button>
      </div>

      {message ? <div className="mt-3 text-sm text-white/65">{message}</div> : null}

      <details className="mt-4 rounded border border-white/10 bg-black/20 p-3">
        <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-white/40">
          Copy curl
        </summary>
        <pre className="mt-3 overflow-auto whitespace-pre-wrap break-all text-xs text-white/60">
          {curl}
        </pre>
      </details>
    </section>
  );
}
