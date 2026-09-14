<script lang="ts">
  import { goto } from '$app/navigation';
  import { getBrowserClient } from '$lib/aragora';

  let task = '';
  let selectedAgents = ['claude', 'gpt-4', 'gemini'];
  let rounds = 5;
  let loading = false;
  let error = '';

  const agents = [
    { id: 'claude', name: 'Claude', provider: 'Anthropic' },
    { id: 'gpt-4', name: 'GPT-4', provider: 'OpenAI' },
    { id: 'gemini', name: 'Gemini', provider: 'Google' },
    { id: 'grok', name: 'Grok', provider: 'xAI' },
    { id: 'mistral', name: 'Mistral Large', provider: 'Mistral' },
  ];

  function toggleAgent(agentId: string) {
    if (selectedAgents.includes(agentId)) {
      selectedAgents = selectedAgents.filter((id) => id !== agentId);
    } else {
      selectedAgents = [...selectedAgents, agentId];
    }
  }

  async function handleSubmit() {
    if (!task.trim()) {
      error = 'Please enter a debate topic';
      return;
    }
    if (selectedAgents.length < 2) {
      error = 'Please select at least 2 agents';
      return;
    }

    loading = true;
    error = '';

    try {
      const client = getBrowserClient();
      const result = await client.debates.create({
        task: task.trim(),
        agents: selectedAgents,
        rounds,
      });

      goto(`/debates/${result.debate_id}`);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to create debate';
      loading = false;
    }
  }
</script>

<h1>Create New Debate</h1>

<form on:submit|preventDefault={handleSubmit}>
  <div class="form-group">
    <label for="task">Debate Topic</label>
    <textarea
      id="task"
      class="input"
      bind:value={task}
      placeholder="What question should the agents debate?"
      rows="4"
    ></textarea>
  </div>

  <fieldset class="form-group">
    <legend>Select Agents ({selectedAgents.length} selected)</legend>
    <div class="agent-list">
      {#each agents as agent}
        <button
          type="button"
          class="agent-button"
          class:selected={selectedAgents.includes(agent.id)}
          aria-pressed={selectedAgents.includes(agent.id)}
          on:click={() => toggleAgent(agent.id)}
        >
          {agent.name}
          <span class="provider">({agent.provider})</span>
        </button>
      {/each}
    </div>
  </fieldset>

  <div class="form-group">
    <label for="rounds">Number of Rounds: {rounds}</label>
    <input type="range" id="rounds" min="3" max="9" bind:value={rounds} />
    <div class="range-labels">
      <span>3 (Quick)</span>
      <span>9 (Thorough)</span>
    </div>
  </div>

  {#if error}
    <div class="error">{error}</div>
  {/if}

  <button type="submit" class="button submit" disabled={loading}>
    {loading ? 'Creating...' : 'Start Debate'}
  </button>
</form>

<style>
  h1 {
    margin-bottom: 2rem;
  }

  .form-group {
    margin-bottom: 1.5rem;
  }

  fieldset {
    border: 0;
    padding: 0;
    min-width: 0;
  }

  label, legend {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 500;
  }

  textarea {
    resize: vertical;
  }

  .agent-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .agent-button {
    padding: 0.5rem 1rem;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    background: transparent;
    color: var(--text);
    cursor: pointer;
    transition: all 0.2s;
  }

  .agent-button.selected {
    background: var(--primary);
    border-color: var(--primary);
  }

  .provider {
    font-size: 0.75rem;
    opacity: 0.7;
    margin-left: 0.25rem;
  }

  input[type="range"] {
    width: 100%;
  }

  .range-labels {
    display: flex;
    justify-content: space-between;
    color: var(--text-muted);
    font-size: 0.875rem;
  }

  .error {
    padding: 1rem;
    background: #fee2e2;
    color: #991b1b;
    border-radius: 0.5rem;
    margin-bottom: 1rem;
  }

  .submit {
    width: 100%;
  }
</style>
