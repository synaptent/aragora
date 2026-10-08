# Aragora Remix Template

A starter template for building Aragora-powered applications with Remix.

## Features

- Server-side data loading with loaders
- Form handling with actions
- Progressive enhancement
- TypeScript throughout

## Quick Start

```bash
# Install dependencies
npm ci

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
ARAGORA_API_URL=http://localhost:8080
ARAGORA_API_KEY=your-api-key
VITE_ARAGORA_API_URL=http://localhost:8080
VITE_ARAGORA_WS_URL=ws://localhost:8765/ws
```

`ARAGORA_API_KEY` stays in server loaders and actions. The `VITE_` variables are
public browser configuration, embedded at build time; never put a private key
in them. Set the public WebSocket URL to your backend's listener (the local
separate listener commonly uses port 8765). If omitted, the SDK derives `/ws`
from the public API URL. Browser streaming requires a backend reachable by the
browser and its normal authentication policy; this template does not forward
the server API key to the browser.

## Validation

Validated with Node 24 and the published `@aragora/sdk` 2.7.4:

```bash
npm ci
npm test
npm run typecheck
npm run build
```

The tests exercise the installed SDK's event envelope, reconnect subscription,
and connection cleanup, plus optional metrics and historical message projection.
The UI uses `rounds_used`, round messages, and the reported consensus result;
missing confidence or agreement is shown as "Not reported" rather than zero.
It retains at most 200 live events for the selected debate.

This example retains its existing Remix 2 dependency line. At validation,
`npm audit` reports inherited dependency vulnerabilities; the consumer fixes
are not a security clearance or a production-deployment recommendation. Resolve
the framework/dependency advisories under a separate reviewed upgrade scope.

## Project Structure

```
app/
  aragora.server.ts      # SDK client (server-only)
  root.tsx               # Root layout
  root.css               # Global styles
  routes/
    _index.tsx           # Home page
    debates._index.tsx   # Debates list
    debates.new.tsx      # Create debate form
    debates.$id.tsx      # Debate detail and live stream
```

## Key Patterns

### Data Loading with Loaders

```typescript
// routes/debates._index.tsx
import { json } from '@remix-run/node';
import { getClient } from '../aragora.server';

export async function loader() {
  const client = getClient();
  const response = await client.debates.list();
  return json({ debates: response.debates });
}
```

### Form Actions

```typescript
// routes/debates.new.tsx
import { redirect } from '@remix-run/node';
import { getClient } from '../aragora.server';

export async function action({ request }) {
  const formData = await request.formData();
  const task = formData.get('task');

  const client = getClient();
  const result = await client.debates.create({ task });

  return redirect(`/debates/${result.debate_id}`);
}
```

### Progressive Enhancement

Remix forms work without JavaScript:

```tsx
import { Form } from '@remix-run/react';

export default function NewDebate() {
  return (
    <Form method="post">
      <input name="task" />
      <button type="submit">Create</button>
    </Form>
  );
}
```

## Learn More

- [Aragora Documentation](https://docs.aragora.ai)
- [Remix Docs](https://remix.run/docs)
- [@aragora/sdk](https://www.npmjs.com/package/@aragora/sdk)
