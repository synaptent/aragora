/**
 * PR intelligence brief — TypeScript entry point.
 *
 * Foundation slice of #6304. Re-exports the type contracts defined in
 * ``./types.ts`` so consumers can ``import { ReviewBrief } from '@/lib/review'``
 * without reaching into the file structure.
 */

export * from './types';
