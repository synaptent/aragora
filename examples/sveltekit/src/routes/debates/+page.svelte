<script lang="ts">
  import type { PageData } from './$types';
  import { debateView } from '$lib/debate-view';

  export let data: PageData;
</script>

<div class="header">
  <h1>Debates</h1>
  <a href="/debates/new" class="button">New Debate</a>
</div>

{#if data.debates.length === 0}
  <div class="card">
    <p>No debates yet. Create your first debate to get started.</p>
  </div>
{:else}
  <div class="grid">
    {#each data.debates as debate}
      <a href="/debates/{debate.debate_id}" class="debate-card card">
        <div class="debate-header">
          <span class="status status-{debate.status}">{debate.status}</span>
          <span class="date">{new Date(debate.created_at).toLocaleDateString()}</span>
        </div>
        <h3>{debate.task?.slice(0, 60) || 'Untitled'}{debate.task?.length > 60 ? '...' : ''}</h3>
        <p class="meta">
          {debate.agents?.length || 0} agents | Completed rounds: {debateView(debate).roundsCompleted}
        </p>
      </a>
    {/each}
  </div>
{/if}

<style>
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
  }

  .debate-card {
    text-decoration: none;
    color: inherit;
    cursor: pointer;
    transition: border-color 0.2s;
  }

  .debate-card:hover {
    border-color: var(--primary);
  }

  .debate-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 0.5rem;
  }

  .status {
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.875rem;
  }

  .date {
    color: var(--text-muted);
    font-size: 0.875rem;
  }

  h3 {
    margin-bottom: 0.5rem;
  }

  .meta {
    color: var(--text-muted);
    font-size: 0.875rem;
  }
</style>
