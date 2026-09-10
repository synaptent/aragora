/**
 * Lighthouse CI Configuration
 *
 * Configuration for automated Lighthouse performance and accessibility audits.
 * Run with: lhci autorun
 *
 * @see https://github.com/GoogleChrome/lighthouse-ci
 */

module.exports = {
  ci: {
    collect: {
      // URLs to audit
      url: ['http://localhost:3000/', 'http://localhost:3000/debates'],
      numberOfRuns: 3, // Run multiple times for consistency
      settings: {
        preset: 'desktop', // Use desktop settings
        // Throttling for consistent results
        throttling: { cpuSlowdownMultiplier: 1 },
        // Skip network throttling in CI
        disableNetworkThrottling: true,
        disableCpuThrottling: true,
      },
    },

    assert: {
      assertions: {
        // Performance assertions (warnings)
        'categories:performance': ['warn', { minScore: 0.5 }],
        'first-contentful-paint': ['warn', { maxNumericValue: 3000 }],
        'largest-contentful-paint': ['warn', { maxNumericValue: 4000 }],
        'cumulative-layout-shift': ['warn', { maxNumericValue: 0.1 }],
        'total-blocking-time': ['warn', { maxNumericValue: 500 }],

        // Accessibility assertions (errors - must pass)
        'categories:accessibility': ['error', { minScore: 0.8 }],
        'color-contrast': 'error',
        'document-title': 'error',
        'html-has-lang': 'error',
        'image-alt': 'error',
        'link-name': 'error',
        list: 'error',
        listitem: 'error',
        'meta-viewport': 'error',

        // Best practices (warnings)
        'categories:best-practices': ['warn', { minScore: 0.8 }],
        'no-vulnerable-libraries': 'warn',
        'uses-https': 'off', // Disabled for localhost
        'is-on-https': 'off',

        // SEO (warnings)
        'categories:seo': ['warn', { minScore: 0.8 }],
        viewport: 'error',
        'font-size': 'warn',
        'tap-targets': 'warn',

        // PWA - optional for now
        'categories:pwa': 'off',
      },
    },

    upload: {
      // Upload to temporary public storage (free tier)
      target: 'temporary-public-storage',
    },

    // Server configuration
    server: {
      // Use this if you want to persist results
      // storage: {
      //   storageMethod: 'sql',
      //   sqlDialect: 'sqlite',
      //   sqlDatabasePath: './.lighthouseci/db.sql',
      // },
    },
  },
};
