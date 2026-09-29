<script lang="ts">
  import type { PageData } from './$types';
  import DebateStream from '$lib/DebateStream.svelte';
  import { debateView } from '$lib/debate-view';

  export let data: PageData;
  $: debate = data.debate;
  $: view = debateView(debate);
</script>

<div>
  <div style="margin-bottom: 2rem">
    <span
      class="status-badge"
      class:completed={debate.status === 'completed'}
      class:running={debate.status === 'running'}
    >
      {debate.status}
    </span>
    <h1 style="margin-top: 1rem">{debate.task}</h1>
    <p class="muted">
      Created {new Date(debate.created_at).toLocaleString()}
    </p>
  </div>

  <div class="grid">
    <div class="card">
      <h3>Agents</h3>
      <div class="agent-list">
        {#each debate.agents || [] as agent}
          <span class="agent-tag">{agent}</span>
        {/each}
      </div>
    </div>

    <div class="card">
      <h3>Progress</h3>
      <p>Completed rounds: {view.roundsCompleted}</p>
    </div>
  </div>

  {#if debate.status === 'running'}
    <div class="card" style="margin-top: 1rem">
      <h3>Live Stream</h3>
      {#key debate.debate_id}
        <DebateStream debateId={debate.debate_id} />
      {/key}
    </div>
  {/if}

  {#if debate.status === 'completed' && debate.consensus}
    <div class="card consensus" style="margin-top: 1rem">
      <h3>{debate.consensus.reached ? 'Consensus Reached' : 'No Consensus'}</h3>
      {#if view.answer}<p style="margin-bottom: 1rem">{view.answer}</p>{/if}
      <div class="stats">
        <div>
          <span class="muted">Confidence</span>
          <p class="stat-value">{view.confidence}</p>
        </div>
        <div>
          <span class="muted">Agreement</span>
          <p class="stat-value">
            {view.agreement}
          </p>
        </div>
      </div>
    </div>
  {/if}

  {#if !debate.consensus && view.answer}
    <div class="card"><h3>Final Answer</h3><p>{view.answer}</p></div>
  {/if}

  {#if view.messages.length > 0}
    <div class="card" style="margin-top: 1rem">
      <h3>Debate History</h3>
      <div class="messages">
        {#each view.messages as msg}
          <div class="message">
            <div class="message-header">
              <strong>{msg.agent ?? msg.agent_id ?? 'Unknown agent'}</strong>
              <span class="muted">Round {msg.round}</span>
            </div>
            <p style="white-space: pre-wrap">{msg.content}</p>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
    gap: 1rem;
  }

  .card {
    padding: 1.5rem;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
  }

  .consensus {
    border-color: #3b82f6;
    border-width: 2px;
  }

  .consensus h3 {
    color: #3b82f6;
  }

  .muted {
    opacity: 0.6;
  }

  .status-badge {
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    background: #f3f4f6;
    color: #374151;
  }

  .status-badge.completed {
    background: #dcfce7;
    color: #166534;
  }

  .status-badge.running {
    background: #dbeafe;
    color: #1e40af;
  }

  .agent-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.5rem;
  }

  .agent-tag {
    padding: 0.25rem 0.75rem;
    background: #f3f4f6;
    color: #374151;
    border-radius: 9999px;
    font-size: 0.875rem;
  }

  .stats {
    display: flex;
    flex-wrap: wrap;
    gap: 2rem;
  }

  .stat-value {
    font-size: 1.25rem;
    font-weight: 600;
  }

  .messages {
    max-height: 500px;
    overflow-y: auto;
  }

  .message {
    padding: 1rem;
    border-bottom: 1px solid #e5e7eb;
  }

  .message-header {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    justify-content: space-between;
    margin-bottom: 0.5rem;
  }
</style>
