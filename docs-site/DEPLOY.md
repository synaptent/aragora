# Documentation Site Deployment

The Aragora documentation site is built with [Docusaurus](https://docusaurus.io/) and can be deployed to Vercel.

## Manual Deployment

### First-Time Setup

1. Install Vercel CLI (if not already installed):

   ```bash
   npm i -g vercel
   ```

2. Login to Vercel:

   ```bash
   vercel login
   ```

3. Link the project:

   ```bash
   cd docs-site
   vercel link
   ```

4. Deploy to production:
   ```bash
   cd docs-site
   vercel --prod
   ```

### Subsequent Deployments

```bash
cd docs-site
node scripts/sync-docs.js && npm run build && vercel --prod
```

Or use the npm script:

```bash
npm run deploy
```

## Automated Deployment (GitHub Actions)

After the first manual deployment, configure GitHub Actions for automated deployments.

### Required Secrets

Add these secrets to your GitHub repository settings:

| Secret              | Description                                                                  |
| ------------------- | ---------------------------------------------------------------------------- |
| `VERCEL_TOKEN`      | Your Vercel API token ([create one here](https://vercel.com/account/tokens)) |
| `VERCEL_ORG_ID`     | Found in `.vercel/project.json` after linking                                |
| `VERCEL_PROJECT_ID` | Found in `.vercel/project.json` after linking                                |

### Workflow Triggers

- **Push to main**: Auto-deploys when `docs/` or `docs-site/` changes
- **Manual**: Can be triggered from GitHub Actions tab

## Local Development

```bash
cd docs-site
npm install
npm start
```

Visit http://localhost:3000 to preview the docs.

## Build Locally

```bash
cd docs-site
node scripts/sync-docs.js
npm run build
npm run serve
```

## Troubleshooting

### Broken Links

The build may report broken links. Most are cross-references that need updating in the sync script. The build still succeeds - these are warnings, not errors.

### Build Failures

1. Clear the cache:

   ```bash
   npm run clear
   ```

2. Ensure Node.js 18+:

   ```bash
   node --version
   ```

3. Reinstall dependencies:
   ```bash
   rm -rf node_modules package-lock.json
   npm install
   ```
