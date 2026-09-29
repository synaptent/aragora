// @ts-check
// Docusaurus Configuration for Aragora Documentation Portal
// See: https://docusaurus.io/docs/configuration

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Aragora Documentation',
  tagline: 'Auditable execution control plane for AI-assisted decisions',
  favicon: 'img/favicon.ico',

  // Production URL
  url: 'https://docs.aragora.ai',
  baseUrl: '/',

  // GitHub Pages deployment config (if using)
  organizationName: 'synaptent',
  projectName: 'aragora',

  onBrokenLinks: 'warn',

  // Markdown configuration (v4-compatible format)
  markdown: {
    preprocessor: ({ fileContent }) => fileContent,
    parseFrontMatter: undefined,
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: './sidebars.js',
          editUrl: 'https://github.com/synaptent/aragora/tree/main/docs/',
          showLastUpdateTime: true,
          showLastUpdateAuthor: true,
        },
        blog: {
          showReadingTime: true,
          blogSidebarTitle: 'Recent posts',
          blogSidebarCount: 5,
        },
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  plugins: [
    // OpenAPI documentation plugin
    [
      'docusaurus-plugin-openapi-docs',
      {
        id: 'api',
        docsPluginId: 'classic',
        config: {
          aragora: {
            specPath: '../docs/api/openapi.json',
            outputDir: 'docs/api-reference',
            sidebarOptions: {
              groupPathsBy: 'tag',
            },
          },
        },
      },
    ],
  ],

  themes: ['docusaurus-theme-openapi-docs'],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      // Default to light/warm theme to match aragora.ai
      colorMode: {
        defaultMode: 'light',
        respectPrefersColorScheme: true,
      },

      // Social card
      image: 'img/aragora-social-card.png',

      // Navbar
      navbar: {
        title: 'Aragora',
        logo: {
          alt: 'Aragora Logo',
          src: 'img/logo.svg',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'gettingStartedSidebar',
            position: 'left',
            label: 'Getting Started',
          },
          {
            type: 'docSidebar',
            sidebarId: 'guidesSidebar',
            position: 'left',
            label: 'Guides',
          },
          {
            type: 'docSidebar',
            sidebarId: 'apiSidebar',
            position: 'left',
            label: 'API Reference',
          },
          {
            type: 'docSidebar',
            sidebarId: 'referenceSidebar',
            position: 'left',
            label: 'Reference',
          },
          {
            href: 'https://aragora.ai',
            label: 'aragora.ai',
            position: 'right',
          },
          {
            href: 'https://github.com/synaptent/aragora',
            label: 'GitHub',
            position: 'right',
          },
          {
            href: 'https://status.aragora.ai',
            label: 'Status',
            position: 'right',
          },
        ],
      },

      // Footer
      footer: {
        style: 'light',
        links: [
          {
            title: 'Docs',
            items: [
              {
                label: 'Getting Started',
                to: '/docs/getting-started',
              },
              {
                label: 'API Reference',
                to: '/docs/api-reference',
              },
              {
                label: 'SDK Guide',
                to: '/docs/guides/sdk',
              },
            ],
          },
          {
            title: 'Community',
            items: [
              {
                label: 'GitHub Discussions',
                href: 'https://github.com/synaptent/aragora/discussions',
              },
              {
                label: 'Discord',
                href: 'https://discord.gg/aragora',
              },
              {
                label: 'Twitter',
                href: 'https://twitter.com/aragora_ai',
              },
            ],
          },
          {
            title: 'Company',
            items: [
              {
                label: 'Blog',
                to: '/blog',
              },
              {
                label: 'Privacy Policy',
                href: 'https://aragora.ai/privacy',
              },
              {
                label: 'Terms of Service',
                href: 'https://aragora.ai/terms',
              },
            ],
          },
        ],
        copyright: `Copyright ${new Date().getFullYear()} Aragora. Built with Docusaurus.`,
      },

      // Code blocks
      prism: {
        theme: require('prism-react-renderer').themes.github,
        darkTheme: require('prism-react-renderer').themes.dracula,
        additionalLanguages: ['bash', 'python', 'json', 'yaml', 'typescript'],
      },

      // Search (Algolia) - Configure with real credentials before enabling
      // algolia: {
      //   appId: 'YOUR_ALGOLIA_APP_ID',
      //   apiKey: 'YOUR_ALGOLIA_API_KEY',
      //   indexName: 'aragora-docs',
      //   contextualSearch: true,
      // },

      // Announcement bar
      announcementBar: {
        id: 'proof_first_rc1',
        content:
          'Aragora v2.9.0-rc.1 is out: proof-first PR settlement, calibration gates, and Decision Integrity Core slices. <a href="/docs/contributing/b0-benchmark-truth-status">See the proof surfaces</a>.',
        backgroundColor: '#4F46E5',
        textColor: '#FFFFFF',
        isCloseable: true,
      },
    }),
};

module.exports = config;
