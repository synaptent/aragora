# Aragora Live Dashboard
# Next.js Frontend Dockerfile
#
# Build from the repository root:
#   docker build -f aragora/live/Dockerfile .

# Stage 1: Dependencies
FROM node:20.19-alpine AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Copy TypeScript SDK and locked frontend dependency metadata.
# The package-lock SDK path remains ../../sdk/typescript. Install from /app
# so npm resolves the local SDK dependency to the absolute /sdk/typescript copy.
COPY sdk/typescript/ /sdk/typescript/
RUN cd /sdk/typescript && npm ci --no-audit --no-fund && npm run build
COPY aragora/live/package.json aragora/live/package-lock.json aragora/live/.npmrc /app/
RUN cd /app && npm ci

# Stage 2: Builder
FROM node:20.19-alpine AS builder
WORKDIR /app

# Copy deps from previous stage
COPY --from=deps /app/node_modules /app/node_modules
COPY --from=deps /sdk/typescript /sdk/typescript
COPY aragora/live/ /app/

# Build arguments for API URLs (production defaults)
ARG NEXT_PUBLIC_API_URL=https://api.aragora.ai
ARG NEXT_PUBLIC_WS_URL=wss://api.aragora.ai/ws

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
ENV NEXT_TELEMETRY_DISABLED=1
ENV DOCKER_BUILD=1

# Build the application with production URLs
RUN cd /app && npm run build:local

# Stage 3: Runner
FROM node:20.19-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy built assets
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
