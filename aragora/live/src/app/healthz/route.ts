import packageInfo from '../../../package.json';
import { logger } from '@/lib/logger';

// Pre-render the liveness document so static exports include it too.
export const dynamic = 'force-static';

export function GET(): Response {
  // Static in production; dev executes this per request. Never log headers or query values.
  logger.info({ req: { url: '/healthz/' } }, 'request');
  return Response.json(
    {
      status: 'ok',
      app: 'aragora-live',
      version: packageInfo.version,
      commit: process.env.NEXT_PUBLIC_BUILD_SHA || 'unknown',
    },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}
