<script lang="ts">
  import { onMount } from 'svelte';
  import { getBrowserClient } from './aragora';
  import { connectDebateStream, type StreamEvent } from './debate-stream';

  export let debateId: string;
  let events: StreamEvent[] = [];
  let connected = false;
  let connectionError: string | null = null;

  onMount(() => connectDebateStream(getBrowserClient().createWebSocket(), debateId, {
    onEvent: event => { events = [...events.slice(-199), event]; },
    onConnected: value => { connected = value; },
    onError: value => { connectionError = value; },
  }));
</script>

<p class="connection-status" role="status">
  {connectionError ? `Connection error: ${connectionError}` : connected ? 'Connected' : 'Disconnected'}
</p>

{#if events.length === 0}
  <p>Waiting for events...</p>
{:else}
  <div class="stream-events">
    {#each events as event}
      <div class="stream-event">
        <div class="event-header">
          <strong>{event.type}{#if event.agent} ({event.agent}){/if}</strong>
          <time datetime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString()}</time>
        </div>
        {#if event.content}
          <p>{event.content.slice(0, 200)}{event.content.length > 200 ? '...' : ''}</p>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  .connection-status { margin: 0.5rem 0 1rem; }
  .stream-events { max-height: 24rem; overflow-y: auto; }
  .stream-event { padding: 0.75rem 0; border-top: 1px solid var(--border); }
  .event-header { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.5rem; }
  time { font-size: 0.75rem; color: var(--text-muted); }
</style>
