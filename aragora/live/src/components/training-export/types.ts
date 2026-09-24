/**
 * Training Export Panel Types
 */

export type ExportType = 'sft' | 'dpo' | 'gauntlet';
export type OutputFormat = 'json' | 'jsonl';

// Pipeline status types
export type PipelineStage =
  'idle' | 'collecting' | 'filtering' | 'transforming' | 'exporting' | 'complete' | 'error';

export interface PipelineStatus {
  stage: PipelineStage;
  progress: number;
  message: string;
  recordsProcessed: number;
  totalRecords: number;
}

export interface ExportStats {
  available_exporters: string[];
  export_directory: string;
  exported_files: Array<{
    name: string;
    size_bytes: number;
    created_at: string;
    modified_at: string;
  }>;
  sft_available?: boolean;
}

export interface ExportFormat {
  description: string;
  schema: Record<string, unknown>;
  use_case: string;
}

export interface FormatsResponse {
  formats: { sft: ExportFormat; dpo: ExportFormat; gauntlet: ExportFormat };
  output_formats: string[];
  endpoints: Record<string, string>;
}

export interface ExportResult {
  export_type: string;
  total_records: number;
  parameters: Record<string, unknown>;
  exported_at: string;
  format: string;
  records?: unknown[];
  data?: string;
}

export const STAGE_LABELS: Record<PipelineStage, string> = {
  idle: 'Ready',
  collecting: 'Collecting data...',
  filtering: 'Applying filters...',
  transforming: 'Transforming records...',
  exporting: 'Generating export...',
  complete: 'Export complete!',
  error: 'Export failed',
};

export const STAGE_COLORS: Record<PipelineStage, string> = {
  idle: 'bg-slate-500',
  collecting: 'bg-blue-500',
  filtering: 'bg-cyan-500',
  transforming: 'bg-purple-500',
  exporting: 'bg-green-500',
  complete: 'bg-green-400',
  error: 'bg-red-500',
};
