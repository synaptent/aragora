import packageInfo from '../../../package.json';

// Pre-render the liveness document so static exports include it too.
export const dynamic = 'force-static';

export function GET(): Response {
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
