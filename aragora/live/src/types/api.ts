/**
 * API Types re-exported for convenience.
 *
 * These types are auto-generated from the OpenAPI spec.
 * Run `npm run generate:types` to regenerate.
 *
 * Usage:
 *   import type { paths, components, operations } from '@/types/api';
 *
 *   // Get request body type for an endpoint
 *   type CreateDebateBody = operations['post_api_debates']['requestBody']['content']['application/json'];
 *
 *   // Get response type for an endpoint
 *   type DebateResponse = paths['/api/debates/{debate_id}']['get']['responses']['200']['content']['application/json'];
 */

export type { paths, components, operations } from './api.generated';

// Re-export common component schemas for convenience
import type { components } from './api.generated';

// Type aliases for commonly-used schemas (if available in generated types)
// Note: Run `npm run generate:types` to regenerate types from OpenAPI spec
export type ApiError = components['schemas']['Error'];

// Helper type to extract response data from a path
export type ApiResponse<
  Path extends keyof import('./api.generated').paths,
  Method extends keyof import('./api.generated').paths[Path],
> = import('./api.generated').paths[Path][Method] extends {
  responses: { 200: { content: { 'application/json': infer R } } };
}
  ? R
  : never;

// Helper type to extract request body from a path
export type ApiRequestBody<
  Path extends keyof import('./api.generated').paths,
  Method extends keyof import('./api.generated').paths[Path],
> = import('./api.generated').paths[Path][Method] extends {
  requestBody: { content: { 'application/json': infer B } };
}
  ? B
  : never;
