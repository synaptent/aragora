import { test as base, expect } from '@playwright/test';

/**
 * Extended test fixtures for Aragora E2E tests
 */

// Test data factories
export const testData = {
  debate: {
    simple: {
      topic: 'Should AI systems be open source?',
      agents: ['claude', 'gpt'],
      rounds: 8, // 9-round format default
    },
    complex: {
      topic: 'What is the best approach to implementing rate limiting in distributed systems?',
      agents: ['claude', 'gpt', 'gemini'],
      rounds: 8, // 9-round format default
      options: {
        consensus: 'judge', // Judge-based consensus default
        enableEvidence: true,
      },
    },
  },
  user: { test: { email: 'test@aragora.ai', password: 'test-password-123' } },
};

// Custom page object helpers
export class AragoraPage {
  constructor(private page: import('@playwright/test').Page) {}

  private readonly sensitiveWarningPatterns = [
    /Bearer\s+[A-Za-z0-9\-._~+/]+=*/i,
    /sk-[A-Za-z0-9]{20,}/,
    /ghp_[A-Za-z0-9]{20,}/,
    /xox[baprs]-[A-Za-z0-9-]{10,}/,
    /AKIA[0-9A-Z]{16}/,
    /AIza[0-9A-Za-z\-_]{35}/,
    /password\s*[:=]\s*\S+/i,
    /token\s*[:=]\s*\S+/i,
  ];

  private async isVisible(
    locator: import('@playwright/test').Locator,
    label: string,
    timeout = 1000,
  ) {
    if ((await locator.count()) === 0) {
      return false;
    }
    try {
      return await locator.first().isVisible({ timeout });
    } catch (error) {
      console.warn(`[e2e] Visibility check failed for ${label}:`, error);
      return false;
    }
  }

  private async clickIfVisible(
    locator: import('@playwright/test').Locator,
    label: string,
    timeout = 1000,
  ) {
    if (!(await this.isVisible(locator, label, timeout))) {
      return false;
    }
    try {
      await locator.first().click();
      return true;
    } catch (error) {
      console.warn(`[e2e] Click failed for ${label}:`, error);
      return false;
    }
  }

  private async waitForHidden(
    locator: import('@playwright/test').Locator,
    label: string,
    timeout = 3000,
  ) {
    try {
      await locator.waitFor({ state: 'hidden', timeout });
    } catch (error) {
      console.warn(`[e2e] ${label} did not hide within ${timeout}ms:`, error);
    }
  }

  private async assertNoSensitiveWarningContent(
    locator: import('@playwright/test').Locator,
    label: string,
  ) {
    if ((await locator.count()) === 0) {
      return;
    }
    const warningText = (await locator.first().textContent())?.trim() ?? '';
    if (!warningText) {
      return;
    }
    const matchedPattern = this.sensitiveWarningPatterns.find((pattern) =>
      pattern.test(warningText),
    );
    if (matchedPattern) {
      throw new Error(`[e2e] Potential sensitive content exposed in ${label}: ${matchedPattern}`);
    }
  }

  /**
   * Dismiss the boot sequence animation if present.
   * The boot animation is a full-screen overlay that blocks all pointer events.
   */
  async dismissBootAnimation() {
    const bootOverlay = this.page.locator('[aria-label*="Boot sequence"]');
    if (await this.clickIfVisible(bootOverlay, 'boot animation')) {
      await this.waitForHidden(bootOverlay, 'boot animation', 5000);
    }
  }

  /**
   * Dismiss the onboarding wizard if present.
   * The wizard is shown for first-time visitors.
   */
  async dismissOnboarding() {
    const skipButton = this.page.locator('button:has-text("[SKIP]")');
    if (await this.clickIfVisible(skipButton, 'onboarding skip button')) {
      await this.waitForHidden(this.page.locator('.fixed.z-\\[100\\]'), 'onboarding wizard');
    }
  }

  /**
   * Dismiss the global connectivity warning if present.
   * This fixed-bottom banner can intercept pointer events during E2E runs.
   */
  async dismissConnectivityWarning() {
    const dismissButton = this.page.locator('button[aria-label="Dismiss connectivity warning"]');
    const connectivityWarning = this.page
      .locator('[role="alert"]')
      .filter({ has: dismissButton })
      .first();
    if (await this.isVisible(dismissButton, 'connectivity warning dismiss button')) {
      await this.assertNoSensitiveWarningContent(connectivityWarning, 'connectivity warning');
      await this.clickIfVisible(dismissButton, 'connectivity warning dismiss button');
      await this.waitForHidden(connectivityWarning, 'connectivity warning');
    }
  }

  /**
   * Dismiss the global config warning if present.
   * This fixed-top banner can intercept header clicks during E2E runs.
   */
  async dismissConfigurationWarning() {
    const configurationWarning = this.page
      .locator('[role="alert"]')
      .filter({ hasText: /CONFIG|NEXT_PUBLIC_SUPABASE_URL|Supabase not configured/i })
      .first();

    try {
      await configurationWarning.waitFor({ state: 'visible', timeout: 1500 });
    } catch {
      return;
    }

    const dismissButton = configurationWarning.locator(
      'button[aria-label="Dismiss configuration warning"], button[aria-label="Dismiss warnings"]',
    );
    if (await this.isVisible(dismissButton, 'configuration warning dismiss button')) {
      await this.assertNoSensitiveWarningContent(configurationWarning, 'configuration warning');
      try {
        await dismissButton.first().click({ force: true });
      } catch (error) {
        console.warn('[e2e] Forced config warning dismiss failed; dispatching click event:', error);
        await dismissButton.first().evaluate((button) => {
          button.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        });
      }
      await this.waitForHidden(configurationWarning, 'configuration warning');
    }
  }

  /**
   * Dismiss all overlays (boot animation, onboarding wizard).
   */
  async dismissAllOverlays() {
    await this.page.waitForLoadState('domcontentloaded').catch(() => {});
    await this.dismissBootAnimation();
    await this.dismissOnboarding();
    await this.dismissConnectivityWarning();
    await this.dismissConfigurationWarning();
    await this.dismissToast();
    await this.dismissConfigurationWarning();
  }

  async waitForAppReady() {
    // First dismiss boot animation if present
    await this.dismissBootAnimation();
    // Wait for Next.js hydration
    await this.page.waitForLoadState('domcontentloaded');
    // Wait for any loading spinners to disappear
    await this.waitForHidden(this.page.locator('[data-testid="loading"]'), 'loading spinner');
  }

  async getToast() {
    return this.page.locator('[data-testid="toast"]').first();
  }

  async waitForToast(text: string) {
    await expect(
      this.page.locator('[data-testid="toast"]').filter({ hasText: text }),
    ).toBeVisible();
  }

  async dismissToast() {
    const toast = await this.getToast();
    if (await this.isVisible(toast, 'toast', 0)) {
      await this.clickIfVisible(
        toast.locator('button[aria-label="Close"]'),
        'toast close button',
        0,
      );
    }
  }
}

// Extended test with Aragora fixtures
export const test = base.extend<{ aragoraPage: AragoraPage }>({
  aragoraPage: async ({ page }, use) => {
    const aragoraPage = new AragoraPage(page);
    await use(aragoraPage);
  },
});

export { expect };

// Common selectors
export const selectors = {
  // Navigation
  nav: {
    home: '[data-testid="nav-home"]',
    debates: '[data-testid="nav-debates"]',
    agents: '[data-testid="nav-agents"]',
    plugins: '[data-testid="nav-plugins"]',
    settings: '[data-testid="nav-settings"]',
    workflows: '[data-testid="nav-workflows"]',
    connectors: '[data-testid="nav-connectors"]',
  },
  // Debate creation
  debateInput: {
    topic: '[data-testid="debate-topic-input"]',
    agentSelect: '[data-testid="agent-select"]',
    startButton: '[data-testid="start-debate-button"]',
  },
  // Debate viewer
  debateViewer: {
    container: '[data-testid="debate-viewer"]',
    messages: '[data-testid="debate-messages"]',
    agentPanel: '[data-testid="agent-panel"]',
    exportButton: '[data-testid="export-button"]',
  },
  // Auth
  auth: {
    signInButton: '[data-testid="sign-in-button"]',
    signOutButton: '[data-testid="sign-out-button"]',
    userMenu: '[data-testid="user-menu"]',
  },
  // Landing page
  landing: {
    hero: '[data-testid="hero-section"]',
    cta: '[data-testid="cta-button"]',
    features: '[data-testid="features-section"]',
  },
  // Workflow builder
  workflow: {
    canvas: '[data-testid="workflow-canvas"]',
    nodePalette: '[data-testid="node-palette"]',
    propertyEditor: '[data-testid="property-editor"]',
    saveButton: '[data-testid="save-workflow"]',
    clearButton: '[data-testid="clear-canvas"]',
    templateBrowser: '[data-testid="template-browser"]',
  },
  // Connectors
  connectors: {
    list: '[data-testid="connector-list"]',
    card: '[data-testid="connector-card"]',
    addButton: '[data-testid="add-connector"]',
    syncButton: '[data-testid="sync-button"]',
    deleteButton: '[data-testid="delete-connector"]',
    statusBadge: '[data-testid="connector-status"]',
  },
  // Visualizations
  visualizations: {
    heatmap: '[data-testid="heatmap"]',
    heatmapCell: '[data-testid="heatmap-cell"]',
    beliefGraph: '[data-testid="belief-graph"]',
    cruxPanel: '[data-testid="crux-panel"]',
    cruxCard: '[data-testid="crux-card"]',
    graphNode: '[data-testid="graph-node"]',
    graphEdge: '[data-testid="graph-edge"]',
  },
};

// API mocking helpers
export async function mockApiResponse(
  page: import('@playwright/test').Page,
  url: string | RegExp,
  response: object,
  status = 200,
) {
  await page.route(url, async (route) => {
    await route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  });
}

// Mock debate data for testing
export const mockDebate = {
  id: 'test-debate-123',
  topic: 'Test debate topic',
  status: 'completed',
  created_at: new Date().toISOString(),
  agents: ['claude', 'gpt'],
  messages: [
    { id: 'msg-1', agent: 'claude', role: 'proposer', content: 'I propose that...', round: 1 },
    { id: 'msg-2', agent: 'gpt', role: 'critic', content: 'I critique this because...', round: 1 },
  ],
  consensus: { reached: true, type: 'majority', summary: 'Agents agreed on the main points.' },
};

// Mock agents data
export const mockAgents = [
  { name: 'claude', provider: 'anthropic', status: 'available', elo: 1500 },
  { name: 'gpt', provider: 'openai', status: 'available', elo: 1480 },
  { name: 'gemini', provider: 'google', status: 'available', elo: 1460 },
];

// Mock workflow templates
export const mockWorkflowTemplates = [
  {
    id: 'legal-contract-review',
    name: 'Contract Review',
    description: 'Automated contract analysis workflow',
    industry: 'legal',
    steps: ['extract', 'analyze', 'review', 'approve'],
  },
  {
    id: 'code-security-audit',
    name: 'Security Audit',
    description: 'Code security analysis pipeline',
    industry: 'code',
    steps: ['scan', 'analyze', 'debate', 'report'],
  },
];

// Mock connectors
export const mockConnectors = [
  {
    id: 'conn-1',
    name: 'Production GitHub',
    type: 'github',
    status: 'connected',
    last_sync: new Date().toISOString(),
    documents_indexed: 1500,
  },
  {
    id: 'conn-2',
    name: 'SharePoint Docs',
    type: 'sharepoint',
    status: 'syncing',
    last_sync: new Date(Date.now() - 3600000).toISOString(),
    documents_indexed: 892,
  },
];

// Mock gauntlet heatmap data
export const mockHeatmapData = {
  categories: ['Input Validation', 'Logic Errors', 'Security'],
  cells: [
    { category: 'Input Validation', severity: 'high', count: 2 },
    { category: 'Security', severity: 'critical', count: 1 },
  ],
  total_findings: 3,
};

// Mock belief network data
export const mockBeliefNetwork = {
  nodes: [
    { id: 'node-1', statement: 'Test claim', author: 'claude', centrality: 0.8, is_crux: true },
    { id: 'node-2', statement: 'Supporting claim', author: 'gpt4', centrality: 0.6 },
  ],
  links: [{ source: 'node-1', target: 'node-2', weight: 0.8, type: 'supports' }],
  metadata: { debate_id: 'test', total_claims: 2, crux_count: 1 },
};
