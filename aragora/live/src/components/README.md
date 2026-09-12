# Components Organization

This directory contains React components for the Aragora frontend.

## Current Structure

Components are organized into these categories:

### Feature Directories (Already Organized)

| Directory        | Purpose                   | Examples                            |
| ---------------- | ------------------------- | ----------------------------------- |
| `agent-tabs/`    | Agent activity views      | AgentTabs, IndividualAgentTab       |
| `auth/`          | Authentication UI         | UserMenu, ProtectedRoute            |
| `billing/`       | Subscription & usage      | SubscriptionCard, UsageMetrics      |
| `broadcast/`     | Audio broadcast features  | AudioPlayer, BroadcastPanel         |
| `debate-viewer/` | Debate display components | DebateViewer, TranscriptMessageCard |
| `deep-audit/`    | Deep audit UI             | DeepAuditView, FindingsSection      |
| `gauntlet/`      | Gauntlet mode             | GauntletLive                        |
| `landing/`       | Marketing pages           | HeroSection, Footer                 |
| `shared/`        | Reusable utilities        | PanelContainer, RefreshButton       |

### Root Components (To Be Organized)

Components in the root directory should eventually be moved:

**Panels** → `panels/`

- `*Panel.tsx` files (30+ components)
- Feature-specific panels for the main UI

**Core UI** → `core/`

- ErrorBoundary, LoadingSpinner, Skeleton
- ToastContainer, Tabs, ThemeToggle

**Visualization** → `visualization/`

- ForceGraph, MatrixRain
- ProofVisualizerPanel

**Debate** → `debate/`

- DebateBrowser, DebateInput
- GraphDebateBrowser

## Import Conventions

```typescript
// Feature components
import { DebateViewer } from '@/components/debate-viewer/DebateViewer';

// Shared utilities
import { PanelContainer } from '@/components/shared/PanelContainer';

// Root components (legacy - will be reorganized)
import { AgentPanel } from '@/components/AgentPanel';
```

## Adding New Components

1. Determine the feature area for your component
2. Place in the appropriate directory
3. Export from the directory's index.ts (if exists)
4. Use PascalCase for component files

## Testing

Test files are in `__tests__/` with `.test.tsx` suffix.

```bash
# Run component tests
npm test
```
