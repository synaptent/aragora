# @aragora/sdk

Official TypeScript SDK for the Aragora multi-agent debate platform.

Need a smaller, `/api/v1`-only client or minimal dependencies? Use
`@aragora/client` for legacy compatibility.

## Package Comparison

| Feature | `@aragora/sdk` | `@aragora/client` |
|---------|----------------|-------------------|
| **Best for** | Full platform apps | Lightweight `/api/v1` integrations |
| **API base** | `/api` + `/api/v1` legacy endpoints | `/api/v1` only |
| **API style** | Flat methods + sync wrapper | Namespaced REST client |
| **Workflows / Marketplace / Explainability** | Yes | No |
| **Control Plane / Graph / Matrix / Verification** | Yes | Yes |
| **Retries/backoff** | Built-in | Minimal |
| **WebSocket Streaming** | Yes | Yes |
| **Build format** | ESM + CJS | CJS |

## Installation

```bash
npm install @aragora/sdk
# or
yarn add @aragora/sdk
# or
pnpm add @aragora/sdk
```

## Quick Start

```typescript
import { createClient } from '@aragora/sdk';

const client = createClient({
  baseUrl: 'https://api.aragora.ai',
  apiKey: 'your-api-key'
});

// Create a debate
const result = await client.createDebate({
  task: 'What is the best programming language for web development?',
  agents: ['claude', 'gpt-4', 'gemini'],
  rounds: 3,
  consensus: 'majority'
});

console.log('Debate created:', result.debate_id);

// Get debate result
const debate = await client.getDebate(result.debate_id);
console.log('Final answer:', debate.final_answer);
```

## Sync-Style Client

For simpler code with async/await, use the sync-style wrapper:

```typescript
import { AragoraClientSync } from '@aragora/sdk';

const client = new AragoraClientSync({
  baseUrl: 'https://api.aragora.ai',
  apiKey: 'your-api-key'
});

// Methods return arrays directly instead of wrapped objects
const debates = await client.listDebates();
const templates = await client.browseMarketplace({ category: 'security' });
const categories = await client.getMarketplaceCategories();

// Batch operations with automatic polling
const results = await client.compareExplanations(['debate-1', 'debate-2']);
```

## Real-time Streaming

Stream debate events as they happen using WebSockets:

```typescript
import { createClient } from '@aragora/sdk';

const client = createClient({
  baseUrl: 'https://api.aragora.ai',
  apiKey: 'your-api-key'
});

// Create WebSocket connection
const ws = client.createWebSocket();
await ws.connect();

// Subscribe to a debate
ws.subscribe('debate-id');

// Handle events
ws.on('debate_start', (event) => {
  console.log('Debate started:', event.task);
  console.log('Agents:', event.agents.join(', '));
});

ws.on('agent_message', (event) => {
  console.log(`[Round ${event.round_number}] ${event.agent}: ${event.content}`);
});

ws.on('critique', (event) => {
  console.log(`${event.critic} critiques ${event.target}: ${event.critique}`);
});

ws.on('vote', (event) => {
  console.log(`${event.agent} votes: ${event.vote} (confidence: ${event.confidence})`);
});

ws.on('consensus', (event) => {
  console.log('Consensus reached!');
  console.log('Agreement:', event.consensus.agreement);
  console.log('Final answer:', event.consensus.final_answer);
});

ws.on('debate_end', (event) => {
  console.log('Debate ended with status:', event.status);
  ws.disconnect();
});
```

## Configuration

```typescript
import { createClient } from '@aragora/sdk';

const client = createClient({
  // Required: API base URL
  baseUrl: 'https://api.aragora.ai',

  // Optional: API key for authentication
  apiKey: process.env.ARAGORA_API_KEY,

  // Optional: Request timeout in milliseconds (default: 30000)
  timeout: 60000,

  // Optional: Enable automatic retries (default: true)
  retryEnabled: true,

  // Optional: Maximum retry attempts (default: 3)
  maxRetries: 5,

  // Optional: Additional headers
  headers: {
    'X-Custom-Header': 'value'
  },

  // Optional: WebSocket URL override
  wsUrl: 'wss://ws.aragora.ai'
});
```

## API Reference

### Debates

```typescript
// List debates
const { debates } = await client.listDebates({ limit: 10 });

// Get a specific debate
const debate = await client.getDebate('debate-id');

// Create a debate
const result = await client.createDebate({
  task: 'Your question here',
  agents: ['claude', 'gpt-4'],
  rounds: 3,
  consensus: 'majority' // 'majority' | 'unanimous' | 'weighted' | 'semantic'
});

// Search debates
const { debates } = await client.searchDebates('AI safety');

// Export debate
const markdown = await client.exportDebate('debate-id', 'markdown');
```

### Agents

```typescript
// List all agents
const { agents } = await client.listAgents();

// Get agent details
const agent = await client.getAgent('claude');

// Get agent profile with stats
const profile = await client.getAgentProfile('claude');

// Get leaderboard
const { agents } = await client.getLeaderboard();

// Compare agents
const comparison = await client.compareAgents(['claude', 'gpt-4']);
```

### Explainability

```typescript
// Get full explanation
const explanation = await client.getExplanation('debate-id', {
  include_factors: true,
  include_counterfactuals: true,
  include_provenance: true
});

// Get contributing factors
const factors = await client.getExplanationFactors('debate-id', {
  min_contribution: 0.1
});

// Generate counterfactual
const counterfactual = await client.generateCounterfactual('debate-id', {
  hypothesis: 'What if agent X had a different opinion?',
  affected_agents: ['claude']
});

// Get narrative summary
const narrative = await client.getNarrative('debate-id', {
  format: 'executive_summary'
});
```

### Workflows

```typescript
// List workflow templates with optional tags filter
const { templates } = await client.listWorkflowTemplates({
  category: 'analysis',
  tags: 'security,compliance'
});

// Get a template with examples
const pkg = await client.getWorkflowTemplatePackage('template-id', {
  include_examples: true
});
console.log(pkg.template, pkg.examples);

// Create workflow from pattern
const { template_id, workflow } = await client.instantiatePattern('pattern-id', {
  name: 'My Security Workflow',
  description: 'Custom security analysis',
  category: 'security',
  agents: ['claude', 'gpt-4']
});

// Run a workflow template
const result = await client.runWorkflowTemplate('template-id', {
  inputs: { document: 'content...' }
});

// Create custom workflow
const workflow = await client.createWorkflow({
  name: 'My Workflow',
  steps: [...]
});

// Execute workflow
const { execution_id } = await client.executeWorkflow('workflow-id', {
  input_data: '...'
});
```

### Gauntlet (Decision Receipts)

```typescript
// List receipts
const { receipts } = await client.listGauntletReceipts({
  verdict: 'approved'
});

// Get receipt details
const receipt = await client.getGauntletReceipt('receipt-id');

// Verify receipt integrity
const { valid, hash } = await client.verifyGauntletReceipt('receipt-id');

// Export receipt
const sarif = await client.exportGauntletReceipt('receipt-id', 'sarif');
```

### Template Marketplace

```typescript
// Get marketplace categories
const { categories } = await client.getMarketplaceCategories();

// Browse templates
const { templates } = await client.browseMarketplace({
  category: 'security',
  sort_by: 'downloads'
});

// Import a template
const { imported_id } = await client.importTemplate('template-id');

// Rate a template
await client.rateTemplate('template-id', 5);

// Write a review
const { review_id } = await client.reviewTemplate('template-id', {
  rating: 5,
  title: 'Excellent template',
  content: 'This template saved us hours of work...'
});

// Publish a template with documentation
const { marketplace_id } = await client.publishTemplate({
  template_id: 'my-template',
  name: 'Security Audit',
  description: 'Comprehensive security analysis workflow',
  category: 'security',
  tags: ['audit', 'compliance'],
  documentation: '# Usage\n\nThis template...'
});

// Get featured templates
const { templates } = await client.getFeaturedTemplates();
```

## Namespace APIs (Advanced)

For more granular control, you can access the namespace APIs directly. These provide
access to full CRUD operations and are useful for building admin dashboards or
complex integrations.

```typescript
import { createClient } from '@aragora/sdk';

const client = createClient({ baseUrl: '...', apiKey: '...' });

// Access namespace APIs via client.namespaces
const { DebatesAPI, AgentsAPI, WorkflowsAPI, ControlPlaneAPI } = client.namespaces;

// Debates namespace - full CRUD operations
const debates = new DebatesAPI(client);
const allDebates = await debates.list({ limit: 100, status: 'completed' });
const debate = await debates.get('debate-123');
await debates.delete('debate-123');

// Agents namespace - registry and performance
const agents = new AgentsAPI(client);
const agentList = await agents.list();
const performance = await agents.getPerformance('anthropic-api');

// Workflows namespace - template management
const workflows = new WorkflowsAPI(client);
const templates = await workflows.listTemplates({ category: 'security' });
const execution = await workflows.execute('template-id', { inputs: {...} });

// Control Plane namespace - enterprise orchestration
const controlPlane = new ControlPlaneAPI(client);

// Agent registry
await controlPlane.registerAgent({
  agentId: 'custom-agent',
  capabilities: ['reasoning', 'code_review'],
  metadata: { version: '1.0.0' }
});

const registeredAgents = await controlPlane.listAgents();
const health = await controlPlane.getAgentHealth('anthropic-api');

// Task scheduling
const task = await controlPlane.submitTask({
  taskType: 'debate',
  payload: { question: 'Should we use GraphQL?' },
  priority: 8,
  requiredCapabilities: ['reasoning']
});

const result = await controlPlane.waitForTask(task.taskId, { timeout: 300000 });

// Resource monitoring
const status = await controlPlane.getStatus();
console.log(`Active agents: ${status.activeAgents}`);
console.log(`Pending tasks: ${status.pendingTasks}`);
```

### SME Namespace (Small/Medium Enterprise)

Simplified APIs for common business use cases:

```typescript
const { SMEAPI } = client.namespaces;
const sme = new SMEAPI(client);

// Quick decision making
const decision = await sme.quickDecision({
  question: 'Should we expand to European markets?',
  context: { revenue: 5000000, employees: 50 }
});

// Risk assessment
const risks = await sme.assessRisks({
  proposal: 'Launch new product line',
  budget: 100000
});

// Compliance check
const compliance = await sme.checkCompliance({
  domain: 'gdpr',
  operations: ['user_data_collection', 'third_party_sharing']
});
```

## Error Handling

```typescript
import { AragoraError } from '@aragora/sdk';

try {
  const debate = await client.getDebate('non-existent');
} catch (error) {
  if (error instanceof AragoraError) {
    console.error('API Error:', error.message);
    console.error('Code:', error.code); // e.g., 'NOT_FOUND'
    console.error('Status:', error.status); // e.g., 404
    console.error('Trace ID:', error.traceId);
  }
}
```

## Node.js WebSocket Support

For Node.js environments, install the `ws` package:

```bash
npm install ws
```

The SDK will automatically use it when available.

## TypeScript Support

Full TypeScript support with exported types:

```typescript
import type {
  Debate,
  DebateCreateRequest,
  Agent,
  AgentProfile,
  ConsensusResult,
  Workflow,
  WorkflowTemplate,
  MarketplaceTemplate,
  TemplateReview,
  DecisionReceipt,
  ExplainabilityResult
} from '@aragora/sdk';

// Import both client types
import { AragoraClient, AragoraClientSync } from '@aragora/sdk';
```

## Browser Support

The SDK works in all modern browsers. For older browsers, you may need to polyfill `fetch` and `WebSocket`.

## Development

Regenerate OpenAPI-derived types:

```bash
npm run generate:types
```

Verify generated types are up to date:

```bash
npm run check:types
```

## License

MIT
