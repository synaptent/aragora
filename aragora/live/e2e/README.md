# E2E Tests with Playwright

End-to-end tests for the Aragora Live Dashboard.

## Setup

1. Install dependencies:

   ```bash
   npm install
   ```

2. Install Playwright browsers:
   ```bash
   npx playwright install
   ```

## Running Tests

```bash
# Run all E2E tests
npm run test:e2e

# Run tests with UI mode (recommended for development)
npm run test:e2e:ui

# Run tests in headed mode (see the browser)
npm run test:e2e:headed

# Run tests in debug mode
npm run test:e2e:debug

# View test report
npm run test:e2e:report
```

## Test Structure

- `homepage.spec.ts` - Homepage and navigation tests
- `debates.spec.ts` - Debate listing and detail page tests
- `leaderboard.spec.ts` - Agent ranking and leaderboard tests
- `auth.spec.ts` - Authentication flow tests
- `api-health.spec.ts` - API connectivity and error handling tests

## Running Specific Tests

```bash
# Run only homepage tests
npx playwright test homepage

# Run tests for a specific browser
npx playwright test --project=chromium

# Run tests matching a pattern
npx playwright test -g "should load"
```

## Configuration

Edit `playwright.config.ts` to:

- Change the base URL
- Add/remove browsers
- Adjust timeouts
- Configure the web server

## Writing Tests

```typescript
import { test, expect } from '@playwright/test';

test('example test', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Aragora/);
});
```

## CI Integration

Tests run automatically on CI with:

- Retries enabled (2 retries on failure)
- Single worker for stability
- HTML report generation

## Debugging Failed Tests

1. Run with `--debug` flag
2. Check the HTML report at `playwright-report/`
3. View screenshots and videos in `test-results/`

## Best Practices

- Use `data-testid` attributes for stable selectors
- Prefer user-visible text over implementation details
- Handle loading states explicitly
- Test both happy paths and error cases
