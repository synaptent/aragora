# Aragora SvelteKit Template

A starter template for building Aragora-powered applications with SvelteKit.

## Features

- Server-side data loading with `+page.server.ts`
- Client-side interactivity with Svelte stores
- TypeScript throughout
- Clean, minimal styling

## Quick Start

```bash
# Install dependencies
npm install

# Set up environment variables
cp .env.example .env
# Edit .env with your Aragora API URL and key

# Start development server
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) to see the app.

## Environment Variables

Create a `.env` file:

```bash
# Server-side (private)
ARAGORA_API_URL=http://localhost:8080
ARAGORA_API_KEY=your-api-key

# Client-side (public)
PUBLIC_ARAGORA_API_URL=http://localhost:8080
PUBLIC_ARAGORA_WS_URL=ws://localhost:8765/ws
```

Use the separate WebSocket URL when running `aragora serve --api-port 8080
--ws-port 8765`. Omit it when your API origin also serves `/ws`. Never put the
private API key in a `PUBLIC_` variable. Debate views consume the published
`@aragora/sdk` types; missing confidence and agreement remain "Not reported".

## Project Structure

```
src/
  lib/
    aragora.ts        # SDK client configuration
  routes/
    +layout.svelte    # Root layout
    +page.svelte      # Home page
    debates/
      +page.server.ts # Server-side data loading
      +page.svelte    # Debates list
      new/
        +page.svelte  # Create debate form
```

## Key Patterns

### Server-Side Loading

Use `+page.server.ts` for data fetching:

```typescript
// routes/debates/+page.server.ts
import { getServerClient } from '$lib/aragora.server';

export const load = async () => {
  const client = getServerClient();
  const response = await client.debates.list();
  return { debates: response.debates };
};
```

### Client-Side Actions

```svelte
<script lang="ts">
  import { getBrowserClient } from '$lib/aragora';

  async function createDebate() {
    const client = getBrowserClient();
    await client.debates.create({ task: 'My topic' });
  }
</script>
```

## Validation

```bash
npm ci
npm test
npm run check
npm run build
```

Tests exercise the installed SDK's event envelopes, subscription lifecycle and
debate field mapping without a live provider. `npm run check` checks the Svelte
components and TypeScript together.

## Resources

- [Aragora Documentation](https://docs.aragora.ai)
- [SvelteKit Docs](https://kit.svelte.dev/docs)
- [@aragora/sdk](https://www.npmjs.com/package/@aragora/sdk)
