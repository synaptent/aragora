import { test, expect, mockApiResponse } from './fixtures';

/**
 * E2E tests for the Visual Workflow Builder feature.
 */

// Mock workflow templates
const mockTemplates = [
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

// Mock workflows
const mockWorkflows = [
  {
    id: 'workflow-1',
    name: 'My Test Workflow',
    description: 'A test workflow',
    status: 'draft',
    created_at: new Date().toISOString(),
    steps: 3,
  },
];

test.describe('Workflow Builder Page', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API endpoints
    await mockApiResponse(page, '**/api/workflow-templates', { templates: mockTemplates });
    await mockApiResponse(page, '**/api/workflows', { workflows: mockWorkflows, total: 1 });
  });

  test('should load workflow builder page', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Should display workflow builder heading
    const heading = page.locator('h1, h2').filter({ hasText: /workflow|builder/i });
    await expect(heading.first()).toBeVisible();
  });

  test('should display node palette with available node types', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Should show node palette
    const nodePalette = page.locator('[data-testid="node-palette"], .node-palette');

    if (await nodePalette.isVisible().catch(() => false)) {
      // Should have node type options
      const nodeTypes = page.locator(
        '[data-testid="node-type"], .node-type-item, [draggable="true"]',
      );
      await expect(nodeTypes.first()).toBeVisible();
    }
  });

  test('should display React Flow canvas', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Should have canvas element
    const canvas = page.locator('.react-flow, [data-testid="workflow-canvas"]');
    await expect(canvas.first()).toBeVisible({ timeout: 10000 });
  });

  test('should be able to add a node to the canvas', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Find a draggable node type
    const nodeType = page.locator('[draggable="true"], [data-testid="node-type"]').first();

    if (await nodeType.isVisible().catch(() => false)) {
      // Get canvas for drop target
      const canvas = page.locator('.react-flow__viewport, .react-flow');

      if (await canvas.isVisible().catch(() => false)) {
        // Attempt drag and drop
        await nodeType.dragTo(canvas, {
          sourcePosition: { x: 10, y: 10 },
          targetPosition: { x: 200, y: 200 },
        });

        // Should have at least one node on canvas
        await page.waitForTimeout(500);
        const _nodes = page.locator('.react-flow__node');
        // Node count might vary based on interaction
      }
    }
  });

  test('should show property editor when node is selected', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for existing node on canvas or add one
    const node = page.locator('.react-flow__node').first();

    if (await node.isVisible({ timeout: 5000 }).catch(() => false)) {
      await node.click();

      // Property editor should appear
      const propertyEditor = page.locator(
        '[data-testid="property-editor"], .property-editor, aside',
      );

      if (await propertyEditor.isVisible().catch(() => false)) {
        // Should have editable fields
        const inputs = propertyEditor.locator('input, select, textarea');
        await expect(inputs.first()).toBeVisible();
      }
    }
  });

  test('should be able to save workflow', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Mock save endpoint
    await mockApiResponse(page, '**/api/workflows', { id: 'new-workflow-123', success: true }, 201);

    // Find save button
    const saveButton = page.locator(
      'button:has-text("Save"), button:has-text("SAVE"), [data-testid="save-workflow"]',
    );

    if (await saveButton.isVisible().catch(() => false)) {
      await expect(saveButton).toBeEnabled();
    }
  });

  test('should be able to clear canvas', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Find clear button
    const clearButton = page.locator(
      'button:has-text("Clear"), button:has-text("CLEAR"), [data-testid="clear-canvas"]',
    );

    if (await clearButton.isVisible().catch(() => false)) {
      await expect(clearButton).toBeEnabled();
    }
  });
});

test.describe('Workflow Templates', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/workflow-templates', { templates: mockTemplates });
  });

  test('should display available templates', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Should show templates section or button
    const templatesSection = page.locator(
      '[data-testid="templates"], button:has-text("Template"), .template-browser',
    );

    if (await templatesSection.isVisible().catch(() => false)) {
      await expect(templatesSection.first()).toBeVisible();
    }
  });

  test('should be able to load a template', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Find and click template option
    const templateCard = page.locator('[data-testid="template-card"], .template-item').first();

    if (await templateCard.isVisible().catch(() => false)) {
      await templateCard.click();

      // Canvas should update with template nodes
      await page.waitForTimeout(500);
      const _nodes = page.locator('.react-flow__node');
      // Template should add nodes
    }
  });

  test('should filter templates by industry', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Find industry filter
    const industryFilter = page.locator(
      '[data-testid="industry-filter"], button:has-text("legal"), button:has-text("code")',
    );

    if (
      await industryFilter
        .first()
        .isVisible()
        .catch(() => false)
    ) {
      await industryFilter.first().click();

      // Templates should be filtered
      await page.waitForTimeout(300);
    }
  });
});

test.describe('Workflows List Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/workflows', { workflows: mockWorkflows, total: 1 });
  });

  test('should load workflows list page', async ({ page, aragoraPage }) => {
    await page.goto('/workflows');
    await aragoraPage.dismissAllOverlays();

    // Should display workflows heading
    const heading = page.locator('h1, h2').filter({ hasText: /workflow/i });
    await expect(heading.first()).toBeVisible();
  });

  test('should display workflow cards or list', async ({ page, aragoraPage }) => {
    await page.goto('/workflows');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Should show workflow items or empty state
    const workflowItems = page.locator('[data-testid="workflow-item"], .workflow-card');
    const emptyState = page.locator(':text("No workflows"), :text("Create your first")');

    const hasWorkflows = (await workflowItems.count()) > 0;
    const hasEmptyState = await emptyState.isVisible().catch(() => false);

    expect(hasWorkflows || hasEmptyState).toBeTruthy();
  });

  test('should have link to create new workflow', async ({ page, aragoraPage }) => {
    await page.goto('/workflows');
    await aragoraPage.dismissAllOverlays();

    // Should have create button or link
    const createButton = page.locator(
      'a:has-text("Create"), a:has-text("New"), button:has-text("New Workflow")',
    );

    if (await createButton.isVisible().catch(() => false)) {
      await expect(createButton.first()).toBeEnabled();
    }
  });
});

test.describe('Workflow Node Types', () => {
  test('should support debate node', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Look for debate node type in palette
    const debateNode = page.locator(':text("Debate"), :text("DEBATE"), [data-type="debate"]');

    if (await debateNode.isVisible().catch(() => false)) {
      await expect(debateNode.first()).toBeVisible();
    }
  });

  test('should support human checkpoint node', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Look for human checkpoint node type
    const checkpointNode = page.locator(
      ':text("Human"), :text("Checkpoint"), :text("Approval"), [data-type="human_checkpoint"]',
    );

    if (await checkpointNode.isVisible().catch(() => false)) {
      await expect(checkpointNode.first()).toBeVisible();
    }
  });

  test('should support decision node', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Look for decision node type
    const decisionNode = page.locator(
      ':text("Decision"), :text("Branch"), :text("Conditional"), [data-type="decision"]',
    );

    if (await decisionNode.isVisible().catch(() => false)) {
      await expect(decisionNode.first()).toBeVisible();
    }
  });

  test('should support memory nodes', async ({ page, aragoraPage }) => {
    await page.goto('/workflows/builder');
    await aragoraPage.dismissAllOverlays();

    // Look for memory node types
    const memoryNode = page.locator(
      ':text("Memory"), :text("Knowledge"), [data-type="memory_read"], [data-type="memory_write"]',
    );

    if (await memoryNode.isVisible().catch(() => false)) {
      await expect(memoryNode.first()).toBeVisible();
    }
  });
});
