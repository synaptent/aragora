jest.mock('@playwright/test', () => ({
  defineConfig: <T>(config: T) => config,
  devices: {
    'Desktop Chrome': {},
    'Desktop Firefox': {},
    'Desktop Safari': {},
    'Pixel 5': {},
    'iPhone 12': {},
  },
}));

const {
  default: config,
  CI_SMOKE_TEST_MATCH,
  SPECIALTY_PROJECT_TEST_IGNORE,
} = require('../playwright.config') as typeof import('../playwright.config');

type PlaywrightProject = {
  name?: string;
  testDir?: string;
  testIgnore?: unknown;
  testMatch?: unknown;
};

const projects = (config.projects ?? []) as PlaywrightProject[];

function getProject(name: string): PlaywrightProject {
  const project = projects.find((candidate) => candidate.name === name);
  expect(project).toBeDefined();
  return project as PlaywrightProject;
}

describe('playwright config', () => {
  it('keeps production and specialty suites out of the default browser matrix', () => {
    expect(SPECIALTY_PROJECT_TEST_IGNORE).toContain('**/production/**');

    for (const projectName of [
      'chromium',
      'ci-smoke',
      'firefox',
      'webkit',
      'Mobile Chrome',
      'Mobile Safari',
    ]) {
      expect(getProject(projectName).testIgnore).toEqual(SPECIALTY_PROJECT_TEST_IGNORE);
    }
  });

  it('scopes the CI smoke project to stable PR specs', () => {
    expect(getProject('ci-smoke').testMatch).toEqual(CI_SMOKE_TEST_MATCH);
    expect(CI_SMOKE_TEST_MATCH).toEqual(
      expect.arrayContaining([
        '**/config-validation.spec.ts',
        '**/homepage.spec.ts',
        '**/landing.spec.ts',
        '**/navigation.spec.ts',
      ]),
    );
  });

  it('keeps the specialty projects scoped to their dedicated specs', () => {
    expect(getProject('accessibility').testMatch).toEqual(/accessibility\.spec\.ts/);
    expect(getProject('visual-regression').testMatch).toEqual(/visual-regression\.spec\.ts/);
    expect(getProject('mobile-audit').testDir).toBe('./e2e/mobile');
    expect(getProject('mobile-audit').testMatch).toEqual(/mobile-audit\.spec\.ts/);
  });
});
