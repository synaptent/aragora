'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { ErrorWithRetry } from '@/components/ErrorWithRetry';
import { DeliveryModal } from '@/components/receipts';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useAuthFetch } from '@/hooks/useAuthenticatedFetch';
import { useSWRFetch } from '@/hooks/useSWRFetch';

type ReceiptVerdict = 'PASS' | 'CONDITIONAL' | 'FAIL';
type TabType = 'list' | 'detail';
type ReceiptSource = 'gauntlet-receipts' | 'v2-receipts' | 'gauntlet-results';

interface RiskSummary {
  critical: number;
  high: number;
  medium: number;
  low: number;
}

interface ReceiptListItem {
  id: string;
  source: ReceiptSource;
  status: 'pending' | 'running' | 'blocked' | 'completed' | 'failed';
  receiptId?: string;
  gauntletId?: string;
  debateId?: string;
  verdict?: ReceiptVerdict;
  confidence?: number;
  created_at: string;
  input_summary?: string;
  risk_summary?: RiskSummary;
  risk_level?: string;
  vulnerabilities_found?: number;
}

interface ProvenanceRecord {
  timestamp: string;
  event_type: string;
  agent?: string;
  description: string;
  evidence_hash: string;
}

interface ConsensusProof {
  reached: boolean;
  confidence: number;
  supporting_agents: string[];
  dissenting_agents: string[];
  method: string;
  evidence_hash: string;
}

interface DecisionReceipt {
  receipt_id: string;
  gauntlet_id: string;
  debate_id?: string;
  timestamp: string;
  input_summary: string;
  input_hash: string;
  risk_level?: string;
  risk_summary: RiskSummary;
  attacks_attempted: number;
  attacks_successful: number;
  probes_run: number;
  vulnerabilities_found: number;
  verdict: ReceiptVerdict | 'UNKNOWN';
  confidence: number;
  robustness_score: number;
  vulnerability_details: Array<{
    id: string;
    category: string;
    severity: string;
    description: string;
  }>;
  verdict_reasoning: string;
  dissenting_views: string[];
  consensus_proof?: ConsensusProof;
  provenance_chain: ProvenanceRecord[];
  artifact_hash: string;
  agents_involved: string[];
  rounds_completed: number;
  duration_seconds: number;
  cost_summary?: ReceiptCostSummary;
}

interface ReceiptCostAgentSummary {
  agent_name: string;
  total_cost_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
  call_count: number;
}

interface ReceiptCostSummary {
  total_cost_usd?: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_calls: number;
  per_agent: ReceiptCostAgentSummary[];
}

interface ApiListResponse {
  results?: Array<Record<string, unknown>>;
  receipts?: Array<Record<string, unknown>>;
  data?: Array<Record<string, unknown>>;
}

interface ShareReceiptResponse {
  share_url?: string;
  token?: string;
  expires_at?: string;
}

const EMPTY_RISK_SUMMARY: RiskSummary = { critical: 0, high: 0, medium: 0, low: 0 };

const DEBATE_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;

function safeString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function safeDebateId(value: unknown): string | undefined {
  const candidate = safeString(value);
  if (!candidate) return undefined;
  return DEBATE_ID_PATTERN.test(candidate) ? candidate : undefined;
}

function safeNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function normalizeTimestamp(value: unknown): string {
  if (typeof value === 'string' && value.trim()) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString();
  }

  const numeric = safeNumber(value);
  if (numeric === undefined) return '';

  const millis = numeric < 1_000_000_000_000 ? numeric * 1000 : numeric;
  const parsed = new Date(millis);
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString();
}

function normalizeVerdict(value: unknown): ReceiptVerdict | undefined {
  const verdict = safeString(value)?.toUpperCase();
  switch (verdict) {
    case 'PASS':
    case 'APPROVED':
      return 'PASS';
    case 'CONDITIONAL':
    case 'WARN':
    case 'WARNING':
    case 'NEEDS_REVIEW':
    case 'APPROVED_WITH_CONDITIONS':
      return 'CONDITIONAL';
    case 'FAIL':
    case 'FAILED':
    case 'REJECTED':
      return 'FAIL';
    default:
      return undefined;
  }
}

function normalizeStatus(value: unknown): ReceiptListItem['status'] {
  const status = safeString(value)?.toLowerCase();
  switch (status) {
    case 'pending':
    case 'queued':
    case 'starting':
      return 'pending';
    case 'running':
    case 'active':
    case 'processing':
    case 'in_progress':
      return 'running';
    case 'blocked':
    case 'timeout':
    case 'pending_approval':
      return 'blocked';
    case 'failed':
    case 'error':
    case 'cancelled':
      return 'failed';
    default:
      return 'completed';
  }
}

type ReceiptSurfaceState = 'pending' | 'live' | 'partial' | 'blocked' | 'complete' | 'failed';

function deriveSurfaceState(item: ReceiptListItem): ReceiptSurfaceState {
  switch (item.status) {
    case 'pending':
      return 'pending';
    case 'running':
      return 'live';
    case 'blocked':
      return 'blocked';
    case 'failed':
      return 'failed';
    case 'completed':
      return item.source === 'gauntlet-results' ? 'partial' : 'complete';
  }
}

function getSurfaceLabel(item: ReceiptListItem): string {
  switch (deriveSurfaceState(item)) {
    case 'pending':
      return 'QUEUED';
    case 'live':
      return 'LIVE';
    case 'partial':
      return 'PARTIAL';
    case 'blocked':
      return 'BLOCKED';
    case 'failed':
      return 'FAILED';
    case 'complete':
      return 'COMPLETE';
  }
}

function getSurfaceTone(item: ReceiptListItem): string {
  switch (deriveSurfaceState(item)) {
    case 'pending':
      return 'text-yellow-300 bg-yellow-500/10 border-yellow-500/30';
    case 'live':
      return 'text-blue-300 bg-blue-500/10 border-blue-500/30';
    case 'partial':
      return 'text-orange-300 bg-orange-500/10 border-orange-500/30';
    case 'blocked':
      return 'text-red-300 bg-red-500/10 border-red-500/30';
    case 'failed':
      return 'text-red-400 bg-red-500/20 border-red-500/40';
    case 'complete':
      return 'text-[var(--accent)] bg-[var(--accent)]/10 border-[var(--accent)]/30';
  }
}

function getSourceLabel(item: ReceiptListItem): string {
  switch (item.source) {
    case 'gauntlet-results':
      return 'Result only';
    case 'gauntlet-receipts':
      return 'Canonical receipt';
    case 'v2-receipts':
      return 'Canonical receipt';
  }
}

function getDebateHref(item: ReceiptListItem): string | null {
  return item.debateId ? `/debates/${encodeURIComponent(item.debateId)}` : null;
}

function getSurfaceSummary(item: ReceiptListItem): string {
  switch (deriveSurfaceState(item)) {
    case 'pending':
      return 'Queued for debate execution. No result or proof has been published yet.';
    case 'live':
      return 'Debate is still running. Wait for a published receipt or open the live debate for progress.';
    case 'partial':
      return 'Partial result only. Canonical receipt and proof have not been published yet.';
    case 'blocked':
      return 'Execution is blocked upstream. Fix provider access or the execution gate, then rerun to publish a canonical receipt.';
    case 'failed':
      return 'Debate failed before a canonical receipt was published.';
    case 'complete':
      return 'No summary was published with this canonical receipt yet.';
  }
}

function getSurfaceAction(item: ReceiptListItem): string | null {
  switch (deriveSurfaceState(item)) {
    case 'live':
      return 'Open debate';
    case 'blocked':
      return 'Open debate to inspect the blocker';
    case 'partial':
      return 'Open debate';
    default:
      return null;
  }
}

function normalizeRiskSummary(data: Record<string, unknown>): RiskSummary | undefined {
  const riskSummaryRecord = asRecord(data.risk_summary);
  if (riskSummaryRecord) {
    return {
      critical: safeNumber(riskSummaryRecord.critical) ?? 0,
      high: safeNumber(riskSummaryRecord.high) ?? 0,
      medium: safeNumber(riskSummaryRecord.medium) ?? 0,
      low: safeNumber(riskSummaryRecord.low) ?? 0,
    };
  }

  const countSummary = {
    critical: safeNumber(data.critical_count) ?? 0,
    high: safeNumber(data.high_count) ?? 0,
    medium: safeNumber(data.medium_count) ?? 0,
    low: safeNumber(data.low_count) ?? 0,
  };
  if (Object.values(countSummary).some((count) => count > 0)) {
    return countSummary;
  }

  if (Array.isArray(data.findings)) {
    const summary = { ...EMPTY_RISK_SUMMARY };
    data.findings.forEach((finding) => {
      const record = asRecord(finding);
      const severity = safeString(record?.severity)?.toLowerCase();
      switch (severity) {
        case 'critical':
          summary.critical += 1;
          break;
        case 'high':
          summary.high += 1;
          break;
        case 'medium':
          summary.medium += 1;
          break;
        case 'low':
          summary.low += 1;
          break;
        default:
          break;
      }
    });
    if (Object.values(summary).some((count) => count > 0)) {
      return summary;
    }
  }

  return undefined;
}

function totalFindings(summary?: RiskSummary): number {
  if (!summary) return 0;
  return summary.critical + summary.high + summary.medium + summary.low;
}

function truncateId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 12)}...` : value;
}

function formatDate(value: string): string {
  if (!value) return 'Unavailable';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 'Unavailable' : parsed.toLocaleDateString();
}

function normalizeListItem(
  raw: Record<string, unknown>,
  source: ReceiptSource,
): ReceiptListItem | null {
  const receiptId = safeString(raw.receipt_id) ?? safeString(raw.id);
  const gauntletId = safeString(raw.gauntlet_id) ?? safeString(raw.run_id);
  const fallbackId = safeString(raw.id);
  const id = gauntletId ?? receiptId ?? fallbackId;

  if (!id) return null;

  const riskSummary = normalizeRiskSummary(raw);
  const metadata = asRecord(raw.metadata);

  return {
    id,
    source,
    status: normalizeStatus(raw.status),
    receiptId,
    gauntletId,
    debateId: safeDebateId(raw.debate_id) ?? safeDebateId(metadata?.debate_id),
    verdict: normalizeVerdict(raw.verdict),
    confidence: safeNumber(raw.confidence),
    created_at: normalizeTimestamp(raw.created_at ?? raw.timestamp ?? raw.completed_at),
    input_summary: safeString(raw.input_summary) ?? safeString(raw.decision_summary),
    risk_summary: riskSummary,
    risk_level: safeString(raw.risk_level) ?? safeString(metadata?.risk_level),
    vulnerabilities_found:
      safeNumber(raw.vulnerabilities_found) ??
      safeNumber(raw.findings_count) ??
      totalFindings(riskSummary),
  };
}

function normalizeListResponse(
  response: ApiListResponse | null,
  source: ReceiptSource,
): ReceiptListItem[] {
  const rawItems = response?.receipts ?? response?.results ?? response?.data ?? [];
  return rawItems
    .map((item) => normalizeListItem(item, source))
    .filter((item): item is ReceiptListItem => item !== null);
}

function sameRiskSummary(a?: RiskSummary, b?: RiskSummary): boolean {
  if (!a && !b) return true;
  if (!a || !b) return false;
  return a.critical === b.critical && a.high === b.high && a.medium === b.medium && a.low === b.low;
}

function sameReceiptItem(a: ReceiptListItem, b: ReceiptListItem): boolean {
  return (
    a.id === b.id &&
    a.source === b.source &&
    a.status === b.status &&
    a.receiptId === b.receiptId &&
    a.gauntletId === b.gauntletId &&
    a.debateId === b.debateId &&
    a.verdict === b.verdict &&
    a.confidence === b.confidence &&
    a.created_at === b.created_at &&
    a.input_summary === b.input_summary &&
    a.risk_level === b.risk_level &&
    a.vulnerabilities_found === b.vulnerabilities_found &&
    sameRiskSummary(a.risk_summary, b.risk_summary)
  );
}

function sameReceiptList(a: ReceiptListItem[], b: ReceiptListItem[]): boolean {
  return a.length === b.length && a.every((item, index) => sameReceiptItem(item, b[index]!));
}

function receiptIdentifiers(item: ReceiptListItem): string[] {
  return Array.from(
    new Set(
      [item.receiptId, item.gauntletId, item.id].filter((value): value is string => Boolean(value)),
    ),
  );
}

function hasReceiptFindings(summary?: RiskSummary): boolean {
  return totalFindings(summary) > 0;
}

function mergeReceiptItems(preferred: ReceiptListItem, fallback: ReceiptListItem): ReceiptListItem {
  return {
    ...preferred,
    receiptId: preferred.receiptId ?? fallback.receiptId,
    gauntletId: preferred.gauntletId ?? fallback.gauntletId,
    debateId: preferred.debateId ?? fallback.debateId,
    verdict: preferred.verdict ?? fallback.verdict,
    confidence: preferred.confidence ?? fallback.confidence,
    created_at: preferred.created_at || fallback.created_at,
    input_summary: preferred.input_summary ?? fallback.input_summary,
    risk_summary: hasReceiptFindings(preferred.risk_summary)
      ? preferred.risk_summary
      : (fallback.risk_summary ?? preferred.risk_summary),
    risk_level: preferred.risk_level ?? fallback.risk_level,
    vulnerabilities_found:
      preferred.vulnerabilities_found && preferred.vulnerabilities_found > 0
        ? preferred.vulnerabilities_found
        : (fallback.vulnerabilities_found ?? preferred.vulnerabilities_found),
  };
}

function compareReceiptItems(a: ReceiptListItem, b: ReceiptListItem): number {
  if (a.created_at && b.created_at && a.created_at !== b.created_at) {
    return b.created_at.localeCompare(a.created_at);
  }

  if (a.created_at && !b.created_at) return -1;
  if (!a.created_at && b.created_at) return 1;

  return preferredReceiptId(a).localeCompare(preferredReceiptId(b));
}

function mergeReceiptSources(...sources: ReceiptListItem[][]): ReceiptListItem[] {
  const merged: ReceiptListItem[] = [];
  const identifierToIndex = new Map<string, number>();

  for (const sourceItems of sources) {
    for (const item of sourceItems) {
      const identifiers = receiptIdentifiers(item);
      const existingIndex = identifiers
        .map((identifier) => identifierToIndex.get(identifier))
        .find((index): index is number => index !== undefined);

      if (existingIndex === undefined) {
        const nextIndex = merged.length;
        merged.push(item);
        identifiers.forEach((identifier) => identifierToIndex.set(identifier, nextIndex));
        continue;
      }

      const nextItem = mergeReceiptItems(merged[existingIndex]!, item);
      merged[existingIndex] = nextItem;
      receiptIdentifiers(nextItem).forEach((identifier) =>
        identifierToIndex.set(identifier, existingIndex),
      );
    }
  }

  return merged.sort(compareReceiptItems);
}

function normalizeProvenanceChain(value: unknown): ProvenanceRecord[] {
  if (!Array.isArray(value)) return [];

  return value
    .map((entry): ProvenanceRecord | null => {
      const record = asRecord(entry);
      if (!record) return null;

      return {
        timestamp: normalizeTimestamp(record.timestamp ?? record.created_at),
        event_type: safeString(record.event_type) ?? safeString(record.type) ?? 'event',
        agent: safeString(record.agent) ?? safeString(record.actor) ?? undefined,
        description:
          safeString(record.description) ??
          safeString(record.message) ??
          'No provenance details provided.',
        evidence_hash:
          safeString(record.evidence_hash) ??
          safeString(record.hash) ??
          safeString(record.checksum) ??
          '',
      };
    })
    .filter((entry): entry is ProvenanceRecord => entry !== null);
}

function normalizeConsensusProof(value: unknown): ConsensusProof | undefined {
  const record = asRecord(value);
  if (!record) return undefined;

  const supportingAgents = Array.isArray(record.supporting_agents)
    ? record.supporting_agents
        .map((agent) => safeString(agent))
        .filter((agent): agent is string => Boolean(agent))
    : [];
  const dissentingAgents = Array.isArray(record.dissenting_agents)
    ? record.dissenting_agents
        .map((agent) => safeString(agent))
        .filter((agent): agent is string => Boolean(agent))
    : [];

  return {
    reached: Boolean(record.reached),
    confidence: safeNumber(record.confidence) ?? 0,
    supporting_agents: supportingAgents,
    dissenting_agents: dissentingAgents,
    method: safeString(record.method) ?? 'unknown',
    evidence_hash: safeString(record.evidence_hash) ?? '',
  };
}

function normalizeVulnerabilityDetails(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value
    .map((finding, index) => {
      const record = asRecord(finding);
      if (!record) return null;

      return {
        id: safeString(record.id) ?? safeString(record.title) ?? `finding-${index + 1}`,
        category: safeString(record.category) ?? safeString(record.title) ?? 'Finding',
        severity: safeString(record.severity) ?? 'medium',
        description:
          safeString(record.description) ??
          safeString(record.mitigation) ??
          safeString(record.title) ??
          'No details provided.',
      };
    })
    .filter(
      (
        finding,
      ): finding is { id: string; category: string; severity: string; description: string } =>
        finding !== null,
    );
}

function normalizeDissentingViews(value: unknown): string[] {
  if (!Array.isArray(value)) return [];

  return value
    .map((entry) => {
      if (typeof entry === 'string') return safeString(entry);
      const record = asRecord(entry);
      if (!record) return undefined;

      const reasons = Array.isArray(record.reasons)
        ? record.reasons
            .map((reason) => safeString(reason))
            .filter((reason): reason is string => Boolean(reason))
        : [];
      const primary =
        safeString(record.reason) ??
        safeString(record.summary) ??
        safeString(record.view) ??
        (reasons.length > 0 ? reasons.join('; ') : undefined);
      const agent = safeString(record.agent);
      const alternative = safeString(record.alternative);

      if (primary && agent) {
        return alternative
          ? `${agent}: ${primary} Alternative: ${alternative}`
          : `${agent}: ${primary}`;
      }

      if (primary) {
        return alternative ? `${primary} Alternative: ${alternative}` : primary;
      }

      if (agent && alternative) {
        return `${agent}: Alternative: ${alternative}`;
      }

      return agent ?? alternative;
    })
    .filter((entry): entry is string => Boolean(entry));
}

function normalizeCostSummary(value: unknown): ReceiptCostSummary | undefined {
  const record = asRecord(value);
  if (!record) return undefined;

  const perAgentRecord = asRecord(record.per_agent);
  const perAgent = perAgentRecord
    ? Object.entries(perAgentRecord)
        .map(([agentName, rawEntry]) => {
          const entry = asRecord(rawEntry);
          if (!entry) return null;

          return {
            agent_name: safeString(entry.agent_name) ?? agentName,
            total_cost_usd: safeNumber(entry.total_cost_usd) ?? 0,
            total_tokens_in: safeNumber(entry.total_tokens_in) ?? 0,
            total_tokens_out: safeNumber(entry.total_tokens_out) ?? 0,
            call_count: safeNumber(entry.call_count) ?? 0,
          };
        })
        .filter((entry): entry is ReceiptCostAgentSummary => entry !== null)
    : [];

  const summary = {
    total_cost_usd: safeNumber(record.total_cost_usd),
    total_tokens_in: safeNumber(record.total_tokens_in) ?? 0,
    total_tokens_out: safeNumber(record.total_tokens_out) ?? 0,
    total_calls: safeNumber(record.total_calls) ?? 0,
    per_agent: perAgent,
  };

  if (
    summary.total_cost_usd === undefined &&
    summary.total_tokens_in === 0 &&
    summary.total_tokens_out === 0 &&
    summary.total_calls === 0 &&
    summary.per_agent.length === 0
  ) {
    return undefined;
  }

  return summary;
}

function hasExecutionSummary(receipt: DecisionReceipt): boolean {
  return (
    receipt.duration_seconds > 0 ||
    receipt.rounds_completed > 0 ||
    receipt.agents_involved.length > 0 ||
    Boolean(receipt.cost_summary)
  );
}

function formatDuration(seconds: number): string {
  if (!(seconds > 0)) return 'Unavailable';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds.toFixed(0)}s`;
}

function formatCurrency(value?: number): string {
  if (value === undefined || !Number.isFinite(value)) return 'Unavailable';
  return value >= 1 ? `$${value.toFixed(2)}` : `$${value.toFixed(4)}`;
}

function formatCount(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString() : '0';
}

function normalizeReceiptDetail(
  raw: Record<string, unknown>,
  sourceItem: ReceiptListItem,
): DecisionReceipt {
  const riskSummary = normalizeRiskSummary(raw) ?? EMPTY_RISK_SUMMARY;
  const findings = normalizeVulnerabilityDetails(raw.vulnerability_details ?? raw.findings);

  return {
    receipt_id: safeString(raw.receipt_id) ?? sourceItem.receiptId ?? sourceItem.id,
    gauntlet_id: safeString(raw.gauntlet_id) ?? sourceItem.gauntletId ?? sourceItem.id,
    debate_id: safeDebateId(raw.debate_id) ?? sourceItem.debateId,
    timestamp: normalizeTimestamp(raw.timestamp ?? raw.created_at ?? sourceItem.created_at),
    input_summary: safeString(raw.input_summary) ?? sourceItem.input_summary ?? 'Decision receipt',
    input_hash: safeString(raw.input_hash) ?? safeString(raw.checksum) ?? '',
    risk_level: safeString(raw.risk_level) ?? sourceItem.risk_level,
    risk_summary: riskSummary,
    attacks_attempted: safeNumber(raw.attacks_attempted) ?? 0,
    attacks_successful: safeNumber(raw.attacks_successful) ?? 0,
    probes_run: safeNumber(raw.probes_run) ?? 0,
    vulnerabilities_found:
      safeNumber(raw.vulnerabilities_found) ?? totalFindings(riskSummary) ?? findings.length,
    verdict: normalizeVerdict(raw.verdict) ?? 'UNKNOWN',
    confidence: safeNumber(raw.confidence) ?? sourceItem.confidence ?? 0,
    robustness_score:
      safeNumber(raw.robustness_score) ??
      safeNumber(raw.coverage_score) ??
      safeNumber(raw.verification_coverage) ??
      0,
    vulnerability_details: findings,
    verdict_reasoning:
      safeString(raw.verdict_reasoning) ??
      safeString(raw.decision_summary) ??
      safeString(raw.summary) ??
      '',
    dissenting_views: normalizeDissentingViews(raw.dissenting_views),
    consensus_proof: normalizeConsensusProof(raw.consensus_proof),
    provenance_chain: normalizeProvenanceChain(raw.provenance_chain),
    artifact_hash: safeString(raw.artifact_hash) ?? safeString(raw.checksum) ?? '',
    agents_involved: Array.isArray(raw.agents_involved)
      ? raw.agents_involved
          .map((agent) => safeString(agent))
          .filter((agent): agent is string => Boolean(agent))
      : [],
    rounds_completed: safeNumber(raw.rounds_completed) ?? 0,
    duration_seconds: safeNumber(raw.duration_seconds) ?? 0,
    cost_summary: normalizeCostSummary(raw.cost_summary),
  };
}

function createTimeoutSignal(timeoutMs: number): AbortSignal | undefined {
  if (typeof AbortSignal === 'undefined') return undefined;
  const timeout = (AbortSignal as typeof AbortSignal & { timeout?: (ms: number) => AbortSignal })
    .timeout;
  return typeof timeout === 'function' ? timeout(timeoutMs) : undefined;
}

function buildDetailUrls(item: ReceiptListItem, backendUrl: string): string[] {
  const urls = new Set<string>();

  if (item.receiptId) {
    urls.add(`${backendUrl}/api/v2/receipts/${item.receiptId}`);
  }

  if (!item.receiptId && item.id) {
    urls.add(`${backendUrl}/api/v2/receipts/${item.id}`);
  }

  if (item.gauntletId) {
    urls.add(`${backendUrl}/api/v1/gauntlet/${item.gauntletId}/receipt`);
    urls.add(`${backendUrl}/api/gauntlet/${item.gauntletId}/receipt`);
  }

  return Array.from(urls);
}

function buildExportUrls(
  item: ReceiptListItem,
  backendUrl: string,
  format: 'json' | 'html' | 'markdown',
): string[] {
  const exportFormat = format === 'markdown' ? 'md' : format;
  const urls = new Set<string>();

  if (item.receiptId) {
    urls.add(
      `${backendUrl}/api/v2/receipts/${item.receiptId}/export?format=${exportFormat}&raw=true`,
    );
  }

  if (!item.receiptId && item.id) {
    urls.add(`${backendUrl}/api/v2/receipts/${item.id}/export?format=${exportFormat}&raw=true`);
  }

  if (item.gauntletId) {
    urls.add(`${backendUrl}/api/v1/gauntlet/${item.gauntletId}/receipt?format=${exportFormat}`);
    urls.add(`${backendUrl}/api/gauntlet/${item.gauntletId}/receipt?format=${exportFormat}`);
  }

  return Array.from(urls);
}

function matchesReceiptId(item: ReceiptListItem, requestedId: string): boolean {
  return (
    item.id === requestedId || item.receiptId === requestedId || item.gauntletId === requestedId
  );
}

function preferredReceiptId(item: ReceiptListItem): string {
  return item.receiptId ?? item.gauntletId ?? item.id;
}

function buildReceiptsHref(
  pathname: string,
  searchParams: { toString(): string } | null | undefined,
  receiptId?: string,
): string {
  const params = new URLSearchParams(searchParams?.toString() ?? '');
  if (receiptId) {
    params.set('id', receiptId);
  } else {
    params.delete('id');
  }
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

function buildReceiptShareUrl(backendUrl: string, response: ShareReceiptResponse): string | null {
  const sharePath = safeString(response.share_url);
  if (sharePath) {
    return new URL(sharePath, backendUrl).toString();
  }

  const token = safeString(response.token);
  if (!token) {
    return null;
  }

  return new URL(`/api/v2/receipts/share/${encodeURIComponent(token)}`, backendUrl).toString();
}

export default function ReceiptsPage() {
  const { config } = useBackend();
  const backendUrl = config.api;
  const { getAuthHeaders } = useAuthFetch();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requestedReceiptId = safeString(searchParams.get('id'));
  const autoOpenAttemptRef = useRef<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>('list');
  const [results, setResults] = useState<ReceiptListItem[]>([]);
  const [selectedItem, setSelectedItem] = useState<ReceiptListItem | null>(null);
  const [selectedReceipt, setSelectedReceipt] = useState<DecisionReceipt | null>(null);
  const [selectedReceiptProofHref, setSelectedReceiptProofHref] = useState<string | null>(null);
  const [receiptLoading, setReceiptLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | ReceiptVerdict>('all');
  const [deliveryModalOpen, setDeliveryModalOpen] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareCopied, setShareCopied] = useState(false);
  const [sharePending, setSharePending] = useState(false);

  const {
    data: gauntletReceiptsData,
    error: gauntletReceiptsError,
    isLoading: gauntletReceiptsLoading,
    mutate: mutateGauntletReceipts,
  } = useSWRFetch<ApiListResponse>('/api/v1/gauntlet/receipts?limit=50', {
    refreshInterval: 30000,
    baseUrl: backendUrl,
  });

  const gauntletReceiptItems = normalizeListResponse(gauntletReceiptsData, 'gauntlet-receipts');

  const {
    data: receiptsData,
    error: receiptsError,
    isLoading: receiptsLoading,
    mutate: mutateReceipts,
  } = useSWRFetch<ApiListResponse>('/api/v2/receipts?limit=50', {
    refreshInterval: 30000,
    baseUrl: backendUrl,
  });

  const v2ReceiptItems = normalizeListResponse(receiptsData, 'v2-receipts');

  const shouldFetchGauntletResults =
    !gauntletReceiptsLoading &&
    !receiptsLoading &&
    gauntletReceiptItems.length === 0 &&
    v2ReceiptItems.length === 0;

  const {
    data: gauntletResultsData,
    error: gauntletResultsError,
    isLoading: gauntletResultsLoading,
    mutate: mutateGauntletResults,
  } = useSWRFetch<ApiListResponse>(
    shouldFetchGauntletResults ? '/api/gauntlet/results?limit=50' : null,
    { refreshInterval: 30000, baseUrl: backendUrl },
  );

  const gauntletResultItems = normalizeListResponse(gauntletResultsData, 'gauntlet-results');

  const mergedReceiptItems = mergeReceiptSources(
    v2ReceiptItems,
    gauntletReceiptItems,
    gauntletResultItems,
  );

  const loading =
    results.length === 0 && (gauntletReceiptsLoading || receiptsLoading || gauntletResultsLoading);

  useEffect(() => {
    let nextResults: ReceiptListItem[] = [];
    let nextError: string | null = null;

    if (mergedReceiptItems.length > 0) {
      nextResults = mergedReceiptItems;
    } else {
      const allLoaded = !gauntletReceiptsLoading && !receiptsLoading && !gauntletResultsLoading;

      if (!allLoaded) return;

      if (gauntletReceiptsError && receiptsError && gauntletResultsError) {
        nextError =
          gauntletReceiptsError.message ||
          receiptsError.message ||
          gauntletResultsError.message ||
          'Failed to load receipts';
      }
    }

    setResults((current) => (sameReceiptList(current, nextResults) ? current : nextResults));
    setError((current) => (current === nextError ? current : nextError));
  }, [
    mergedReceiptItems,
    gauntletReceiptsLoading,
    receiptsLoading,
    gauntletResultsLoading,
    gauntletReceiptsError,
    receiptsError,
    gauntletResultsError,
  ]);

  const loadData = useCallback(async () => {
    setError(null);
    await Promise.allSettled([mutateGauntletReceipts(), mutateReceipts(), mutateGauntletResults()]);
  }, [mutateGauntletReceipts, mutateReceipts, mutateGauntletResults]);

  const syncReceiptQuery = useCallback(
    (receiptId?: string) => {
      router.replace(buildReceiptsHref(pathname, searchParams, receiptId));
    },
    [pathname, router, searchParams],
  );

  const fetchReceipt = useCallback(
    async (item: ReceiptListItem, options: { syncUrl?: boolean } = {}) => {
      setReceiptLoading(true);
      setError(null);
      setSelectedReceiptProofHref(null);

      try {
        let lastStatus: number | null = null;

        for (const url of buildDetailUrls(item, backendUrl)) {
          const response = await fetch(url, { signal: createTimeoutSignal(10000) });

          if (!response.ok) {
            lastStatus = response.status;
            continue;
          }

          const data = (await response.json()) as Record<string, unknown>;
          setSelectedItem(item);
          setSelectedReceipt(normalizeReceiptDetail(data, item));
          setSelectedReceiptProofHref(url);
          setActiveTab('detail');
          if (options.syncUrl !== false) {
            syncReceiptQuery(preferredReceiptId(item));
          }
          return;
        }

        throw new Error(lastStatus ? `HTTP ${lastStatus}` : 'Receipt not found');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load receipt');
      } finally {
        setReceiptLoading(false);
      }
    },
    [backendUrl, syncReceiptQuery],
  );

  const clearSelection = useCallback(() => {
    setActiveTab('list');
    setSelectedItem(null);
    setSelectedReceipt(null);
    setSelectedReceiptProofHref(null);
    syncReceiptQuery(undefined);
  }, [syncReceiptQuery]);

  useEffect(() => {
    setShareUrl(null);
    setShareCopied(false);
    setSharePending(false);
  }, [selectedReceipt?.receipt_id]);

  useEffect(() => {
    if (!requestedReceiptId || receiptLoading) return;
    if (selectedItem && matchesReceiptId(selectedItem, requestedReceiptId)) return;

    const match = results.find((item) => matchesReceiptId(item, requestedReceiptId));
    if (!match) return;

    const attemptKey = `${requestedReceiptId}:${match.source}:${match.id}`;
    if (autoOpenAttemptRef.current === attemptKey) return;

    autoOpenAttemptRef.current = attemptKey;
    void fetchReceipt(match, { syncUrl: false });
  }, [fetchReceipt, receiptLoading, requestedReceiptId, results, selectedItem]);

  const downloadReceipt = async (format: 'json' | 'html' | 'markdown') => {
    if (!selectedItem) return;

    try {
      let lastStatus: number | null = null;

      for (const url of buildExportUrls(selectedItem, backendUrl, format)) {
        const response = await fetch(url, { signal: createTimeoutSignal(10000) });

        if (!response.ok) {
          lastStatus = response.status;
          continue;
        }

        const blob = await response.blob();
        const extension = format === 'markdown' ? 'md' : format;
        const objectUrl = URL.createObjectURL(blob);
        const anchor = document.createElement('a');

        anchor.href = objectUrl;
        anchor.download = `receipt-${selectedItem.receiptId ?? selectedItem.id}.${extension}`;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(objectUrl);
        return;
      }

      throw new Error(lastStatus ? `HTTP ${lastStatus}` : 'Download failed');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed');
    }
  };

  const copyReceiptShareUrl = useCallback(async (url: string) => {
    if (!navigator.clipboard?.writeText) {
      throw new Error('Clipboard access is unavailable in this browser');
    }

    await navigator.clipboard.writeText(url);
    setShareCopied(true);
    setTimeout(() => setShareCopied(false), 2000);
  }, []);

  const handleShareReceipt = useCallback(async () => {
    if (!selectedReceipt) {
      return;
    }

    try {
      setError(null);

      if (shareUrl) {
        await copyReceiptShareUrl(shareUrl);
        return;
      }

      const confirmed = window.confirm(
        'Create a public share link for this receipt? Anyone with the tokenized URL can view the receipt until the link expires.',
      );
      if (!confirmed) {
        return;
      }

      setSharePending(true);
      const response = await fetch(
        `${backendUrl}/api/v2/receipts/${encodeURIComponent(selectedReceipt.receipt_id)}/share`,
        {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({ expires_in_hours: 24 }),
        },
      );

      if (!response.ok) {
        throw new Error(`Failed to create share link (HTTP ${response.status})`);
      }

      const data = (await response.json()) as ShareReceiptResponse;
      const resolvedShareUrl = buildReceiptShareUrl(backendUrl, data);
      if (!resolvedShareUrl) {
        throw new Error('Receipt share response did not include a usable link');
      }

      setShareUrl(resolvedShareUrl);
      await copyReceiptShareUrl(resolvedShareUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create share link');
    } finally {
      setSharePending(false);
    }
  }, [backendUrl, copyReceiptShareUrl, getAuthHeaders, selectedReceipt, shareUrl]);

  const getVerdictColor = (verdict?: string) => {
    switch (normalizeVerdict(verdict)) {
      case 'PASS':
        return 'text-[var(--accent)] bg-[var(--accent)]/20 border-[var(--accent)]/30';
      case 'CONDITIONAL':
        return 'text-yellow-400 bg-yellow-500/20 border-yellow-500/30';
      case 'FAIL':
        return 'text-red-400 bg-red-500/20 border-red-500/30';
      default:
        return 'text-text-muted bg-surface border-border';
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity.toLowerCase()) {
      case 'critical':
        return 'text-red-500 bg-red-500/20';
      case 'high':
        return 'text-orange-400 bg-orange-500/20';
      case 'medium':
        return 'text-yellow-400 bg-yellow-500/20';
      case 'low':
        return 'text-blue-400 bg-blue-500/20';
      default:
        return 'text-text-muted bg-surface';
    }
  };

  const filteredResults =
    filter === 'all' ? results : results.filter((result) => result.verdict === filter);

  const renderResultsList = () => (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">
          Decision Receipts
        </h2>
        <div className="flex gap-2">
          {(['all', 'PASS', 'CONDITIONAL', 'FAIL'] as const).map((value) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={`px-3 py-1 text-xs font-theme-data rounded border transition-colors ${
                filter === value
                  ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                  : 'border-border text-text-muted hover:border-[var(--accent)]/50'
              }`}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      {filteredResults.length === 0 ? (
        <div className="p-8 bg-surface border border-border rounded-lg text-center space-y-4">
          <div className="text-2xl font-theme-data text-[var(--accent)]/40">[ ]</div>
          <p className="text-text font-theme-data font-bold">No decision receipts yet</p>
          <p className="text-text-muted font-theme-data text-sm max-w-md mx-auto">
            Receipts are generated when a debate completes. Each receipt includes the verdict, risk
            analysis, consensus proof, and a tamper-proof audit trail.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
            <Link
              href="/oracle"
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors"
            >
              Ask the Oracle
            </Link>
            <Link
              href="/debate"
              className="px-4 py-2 border border-border text-text-muted font-theme-data text-sm rounded hover:border-[var(--accent)]/50 hover:text-[var(--accent)] transition-colors"
            >
              Start a debate
            </Link>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredResults.map((result) => {
            const displayId = result.receiptId ?? result.gauntletId ?? result.id;
            const dateLabel = formatDate(result.created_at);
            const surfaceLabel = getSurfaceLabel(result);
            const sourceLabel = getSourceLabel(result);
            const surfaceSummary = getSurfaceSummary(result);
            const surfaceAction = getSurfaceAction(result);
            const debateHref = getDebateHref(result);
            const isClickable = deriveSurfaceState(result) === 'complete';

            return (
              <div
                key={`${result.source}:${result.id}`}
                onClick={() => {
                  if (isClickable) {
                    void fetchReceipt(result);
                  }
                }}
                onKeyDown={(event) => {
                  if (isClickable && (event.key === 'Enter' || event.key === ' ')) {
                    event.preventDefault();
                    void fetchReceipt(result);
                  }
                }}
                role={isClickable ? 'button' : undefined}
                tabIndex={isClickable ? 0 : undefined}
                className={`w-full p-4 bg-surface border border-border rounded-lg text-left transition-all ${
                  isClickable ? 'hover:border-[var(--accent)]/50 cursor-pointer' : ''
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <span className="font-theme-data text-sm text-text-muted">
                      {truncateId(displayId)}
                    </span>
                    <span
                      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${getSurfaceTone(result)}`}
                    >
                      {surfaceLabel}
                    </span>
                    <span className="text-xs font-theme-data text-text-muted">{sourceLabel}</span>
                    {result.verdict && (
                      <span
                        className={`px-2 py-0.5 text-xs font-theme-data rounded border ${getVerdictColor(result.verdict)}`}
                      >
                        {result.verdict}
                      </span>
                    )}
                    {typeof result.confidence === 'number' && (
                      <span className="text-xs font-theme-data text-text-muted">
                        {(result.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-text-muted">{dateLabel}</span>
                </div>

                {result.input_summary ? (
                  <p className="text-sm text-text mb-2 line-clamp-1">{result.input_summary}</p>
                ) : (
                  <p className="text-sm text-text-muted mb-2">{surfaceSummary}</p>
                )}

                {result.input_summary && deriveSurfaceState(result) !== 'complete' && (
                  <p className="text-sm text-text-muted mb-2">{surfaceSummary}</p>
                )}

                {result.risk_summary && totalFindings(result.risk_summary) > 0 ? (
                  <div className="flex gap-3 text-xs font-theme-data">
                    {result.risk_summary.critical > 0 && (
                      <span className="text-red-400">C:{result.risk_summary.critical}</span>
                    )}
                    {result.risk_summary.high > 0 && (
                      <span className="text-orange-400">H:{result.risk_summary.high}</span>
                    )}
                    {result.risk_summary.medium > 0 && (
                      <span className="text-yellow-400">M:{result.risk_summary.medium}</span>
                    )}
                    {result.risk_summary.low > 0 && (
                      <span className="text-blue-400">L:{result.risk_summary.low}</span>
                    )}
                  </div>
                ) : result.risk_level ? (
                  <div className="text-xs font-theme-data text-text-muted">
                    Risk: {result.risk_level}
                  </div>
                ) : null}

                {surfaceAction && debateHref && (
                  <div className="mt-3">
                    <Link
                      href={debateHref}
                      className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
                    >
                      {surfaceAction}
                    </Link>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );

  const renderReceiptDetail = () => {
    if (receiptLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <div className="text-[var(--accent)] font-theme-data animate-pulse">
            Loading receipt...
          </div>
        </div>
      );
    }

    if (!selectedReceipt) {
      return <p className="text-text-muted">No receipt selected</p>;
    }

    const receipt = selectedReceipt;
    const findingCount = totalFindings(receipt.risk_summary);
    const totalTokens =
      (receipt.cost_summary?.total_tokens_in ?? 0) + (receipt.cost_summary?.total_tokens_out ?? 0);
    const resultHref = receipt.debate_id
      ? `/debates/${encodeURIComponent(receipt.debate_id)}`
      : null;
    const canonicalProofHref = selectedReceiptProofHref;
    const shareButtonLabel = sharePending
      ? 'Sharing...'
      : shareCopied
        ? 'Copied!'
        : shareUrl
          ? 'Copy link'
          : 'Share link';

    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">
              Decision Receipt
            </h2>
            <div className="text-xs text-text-muted font-theme-data mt-1">
              ID: {receipt.receipt_id}
              {receipt.artifact_hash ? ` | Artifact: ${truncateId(receipt.artifact_hash)}` : ''}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={clearSelection}
              className="px-3 py-1 text-sm font-theme-data border border-border rounded hover:border-[var(--accent)]/50"
            >
              Back
            </button>
            {canonicalProofHref && (
              <a
                href={canonicalProofHref}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-1 text-sm font-theme-data border border-[var(--accent)]/40 text-[var(--accent)] rounded hover:bg-[var(--accent)]/10"
              >
                Canonical proof
              </a>
            )}
            {resultHref && (
              <Link
                href={resultHref}
                className="px-3 py-1 text-sm font-theme-data bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)] text-[var(--acid-cyan)] rounded hover:bg-[var(--acid-cyan)]/30"
              >
                View result
              </Link>
            )}
            <button
              onClick={() => void handleShareReceipt()}
              disabled={sharePending}
              className="px-3 py-1 text-sm font-theme-data bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] rounded hover:bg-[var(--accent)]/30 disabled:opacity-60 disabled:cursor-wait"
            >
              {shareButtonLabel}
            </button>
            <button
              onClick={() => setDeliveryModalOpen(true)}
              className="px-3 py-1 text-sm font-theme-data bg-blue-500/20 border border-blue-500 text-blue-400 rounded hover:bg-blue-500/30"
            >
              Deliver
            </button>
            <div className="relative group">
              <button className="px-3 py-1 text-sm font-theme-data bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] rounded">
                Export
              </button>
              <div className="absolute right-0 mt-1 w-32 bg-surface border border-border rounded shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-10">
                <button
                  onClick={() => downloadReceipt('json')}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-bg"
                >
                  JSON
                </button>
                <button
                  onClick={() => downloadReceipt('html')}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-bg"
                >
                  HTML
                </button>
                <button
                  onClick={() => downloadReceipt('markdown')}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-bg"
                >
                  Markdown
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className={`p-4 rounded-lg border-2 ${getVerdictColor(receipt.verdict)}`}>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-2xl font-theme-data font-bold">{receipt.verdict}</div>
              <div className="text-sm opacity-80">
                Confidence: {(receipt.confidence * 100).toFixed(1)}%
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm">Robustness Score</div>
              <div className="text-2xl font-theme-data font-bold">
                {(receipt.robustness_score * 100).toFixed(0)}%
              </div>
            </div>
          </div>
          {receipt.verdict_reasoning && (
            <p className="mt-3 text-sm opacity-90">{receipt.verdict_reasoning}</p>
          )}
        </div>

        {hasExecutionSummary(receipt) && (
          <div className="p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
              Execution Summary
            </h3>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <div>
                <div className="text-xs text-text-muted">Duration</div>
                <div className="text-xl font-theme-data text-text">
                  {formatDuration(receipt.duration_seconds)}
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Rounds</div>
                <div className="text-xl font-theme-data text-text">
                  {receipt.rounds_completed || 'Unavailable'}
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Agents</div>
                <div className="text-xl font-theme-data text-text">
                  {receipt.agents_involved.length || 'Unavailable'}
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Total Cost</div>
                <div className="text-xl font-theme-data text-[var(--accent)]">
                  {formatCurrency(receipt.cost_summary?.total_cost_usd)}
                </div>
              </div>
            </div>

            {receipt.cost_summary && (
              <>
                <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-4 border-t border-border pt-4">
                  <div>
                    <div className="text-xs text-text-muted">API Calls</div>
                    <div className="text-lg font-theme-data text-text">
                      {formatCount(receipt.cost_summary.total_calls)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-text-muted">Tokens In</div>
                    <div className="text-lg font-theme-data text-text">
                      {formatCount(receipt.cost_summary.total_tokens_in)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-text-muted">Total Tokens</div>
                    <div className="text-lg font-theme-data text-text">
                      {formatCount(totalTokens)}
                    </div>
                  </div>
                </div>

                {receipt.cost_summary.per_agent.length > 0 && (
                  <div className="mt-4 border-t border-border pt-4">
                    <h4 className="text-xs font-theme-data font-bold text-text-muted uppercase mb-3">
                      Per-Agent Cost
                    </h4>
                    <div className="space-y-2">
                      {receipt.cost_summary.per_agent.map((agent) => (
                        <div
                          key={agent.agent_name}
                          className="flex items-center justify-between gap-3 rounded bg-bg px-3 py-2 text-sm"
                        >
                          <div className="font-theme-data text-text">{agent.agent_name}</div>
                          <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted">
                            <span>
                              {formatCount(agent.total_tokens_in + agent.total_tokens_out)} tokens
                            </span>
                            <span>{formatCount(agent.call_count)} calls</span>
                            <span className="text-[var(--acid-cyan)]">
                              {formatCurrency(agent.total_cost_usd)}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        <div className="p-4 bg-surface border border-border rounded-lg">
          <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
            Risk Summary
          </h3>
          {receipt.risk_level && (
            <div className="text-xs font-theme-data text-text-muted mb-3">
              Overall risk level: {receipt.risk_level}
            </div>
          )}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="text-center">
              <div className="text-3xl font-theme-data font-bold text-red-500">
                {receipt.risk_summary.critical}
              </div>
              <div className="text-xs text-text-muted">Critical</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-theme-data font-bold text-orange-400">
                {receipt.risk_summary.high}
              </div>
              <div className="text-xs text-text-muted">High</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-theme-data font-bold text-yellow-400">
                {receipt.risk_summary.medium}
              </div>
              <div className="text-xs text-text-muted">Medium</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-theme-data font-bold text-blue-400">
                {receipt.risk_summary.low}
              </div>
              <div className="text-xs text-text-muted">Low</div>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-4 text-center border-t border-border pt-4">
            <div>
              <div className="text-xl font-theme-data">{receipt.attacks_attempted}</div>
              <div className="text-xs text-text-muted">Attacks Attempted</div>
            </div>
            <div>
              <div className="text-xl font-theme-data">{receipt.attacks_successful}</div>
              <div className="text-xs text-text-muted">Successful</div>
            </div>
            <div>
              <div className="text-xl font-theme-data">{receipt.probes_run}</div>
              <div className="text-xs text-text-muted">Probes Run</div>
            </div>
          </div>
          {findingCount === 0 && receipt.vulnerabilities_found === 0 && (
            <p className="mt-4 text-sm text-text-muted">
              This receipt does not include per-severity finding counts.
            </p>
          )}
        </div>

        {receipt.consensus_proof && (
          <div className="p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
              Consensus Proof
            </h3>
            <div className="flex items-center gap-4 mb-3">
              <span
                className={`px-2 py-1 text-xs font-theme-data rounded ${
                  receipt.consensus_proof.reached
                    ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                    : 'bg-red-500/20 text-red-400'
                }`}
              >
                {receipt.consensus_proof.reached ? 'Consensus Reached' : 'No Consensus'}
              </span>
              <span className="text-sm text-text-muted">
                Method: {receipt.consensus_proof.method} | Confidence:{' '}
                {(receipt.consensus_proof.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div>
                <div className="text-xs text-text-muted mb-1">Supporting Agents</div>
                <div className="flex flex-wrap gap-1">
                  {receipt.consensus_proof.supporting_agents.map((agent) => (
                    <span
                      key={agent}
                      className="px-2 py-0.5 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] rounded"
                    >
                      {agent}
                    </span>
                  ))}
                </div>
              </div>
              {receipt.consensus_proof.dissenting_agents.length > 0 && (
                <div>
                  <div className="text-xs text-text-muted mb-1">Dissenting Agents</div>
                  <div className="flex flex-wrap gap-1">
                    {receipt.consensus_proof.dissenting_agents.map((agent) => (
                      <span
                        key={agent}
                        className="px-2 py-0.5 text-xs font-theme-data bg-red-500/10 text-red-400 rounded"
                      >
                        {agent}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {receipt.vulnerability_details.length > 0 && (
          <div className="p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
              Vulnerabilities ({receipt.vulnerability_details.length})
            </h3>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {receipt.vulnerability_details.map((vulnerability) => (
                <div key={vulnerability.id} className="p-2 bg-bg rounded">
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={`px-1.5 py-0.5 text-xs font-theme-data rounded ${getSeverityColor(vulnerability.severity)}`}
                    >
                      {vulnerability.severity.toUpperCase()}
                    </span>
                    <span className="text-xs text-text-muted">{vulnerability.category}</span>
                    <span className="text-xs text-text-muted font-theme-data">
                      {vulnerability.id}
                    </span>
                  </div>
                  <p className="text-sm text-text">{vulnerability.description}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {receipt.dissenting_views.length > 0 && (
          <div className="p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
              Dissenting Views
            </h3>
            <div className="space-y-2">
              {receipt.dissenting_views.map((view) => (
                <p key={view} className="text-sm text-text">
                  {view}
                </p>
              ))}
            </div>
          </div>
        )}

        {receipt.provenance_chain.length > 0 && (
          <div className="p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
              Provenance Chain
            </h3>
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {receipt.provenance_chain.map((record, index) => (
                <div
                  key={`${record.event_type}-${index}`}
                  className="flex items-start gap-3 text-xs"
                >
                  <div className="w-20 text-text-muted shrink-0">
                    {record.timestamp ? new Date(record.timestamp).toLocaleTimeString() : '--:--'}
                  </div>
                  <div className="px-1.5 py-0.5 bg-blue-500/20 text-blue-400 rounded font-theme-data shrink-0">
                    {record.event_type}
                  </div>
                  {record.agent && (
                    <div className="text-[var(--accent)] shrink-0">{record.agent}</div>
                  )}
                  <div className="text-text flex-1">{record.description}</div>
                  {record.evidence_hash && (
                    <div
                      className="text-text-muted font-theme-data shrink-0"
                      title={record.evidence_hash}
                    >
                      #{record.evidence_hash.slice(0, 8)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="p-4 bg-surface border border-border rounded-lg">
          <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
            Input & Integrity
          </h3>
          <div className="space-y-2 text-sm">
            <div>
              <span className="text-text-muted">Input Summary: </span>
              <span className="text-text">{receipt.input_summary}</span>
            </div>
            <div className="font-theme-data text-xs">
              <span className="text-text-muted">Input Hash: </span>
              <span className="text-text">{receipt.input_hash || 'Unavailable'}</span>
            </div>
            <div className="font-theme-data text-xs">
              <span className="text-text-muted">Artifact Hash: </span>
              <span className="text-text">{receipt.artifact_hash || 'Unavailable'}</span>
            </div>
            <div className="font-theme-data text-xs">
              <span className="text-text-muted">Timestamp: </span>
              <span className="text-text">{receipt.timestamp || 'Unavailable'}</span>
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-bg text-text relative overflow-hidden">
      <Scanlines />
      <CRTVignette />

      <div className="max-w-6xl mx-auto px-4 py-8 relative z-10">
        <div className="mb-8">
          <h1 className="text-xl font-theme-data font-bold text-[var(--accent)] mb-2">
            Decision Receipts
          </h1>
          <p className="text-text-muted font-theme-data text-sm">
            Audit-ready records of every AI-debated decision
          </p>
        </div>

        {error && (
          <div className="mb-6">
            <ErrorWithRetry error={error} onRetry={loadData} />
          </div>
        )}

        <PanelErrorBoundary panelName="Decision Receipts">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="text-[var(--accent)] font-theme-data animate-pulse">Loading...</div>
            </div>
          ) : (
            <div>
              {activeTab === 'list' && renderResultsList()}
              {activeTab === 'detail' && renderReceiptDetail()}
            </div>
          )}
        </PanelErrorBoundary>
      </div>

      {selectedReceipt && (
        <DeliveryModal
          isOpen={deliveryModalOpen}
          onClose={() => setDeliveryModalOpen(false)}
          receiptId={selectedReceipt.receipt_id}
          receiptSummary={selectedReceipt.input_summary}
          apiUrl={backendUrl}
          onDeliverySuccess={() => {
            // Delivery history remains server-backed; no local mutation needed here.
          }}
        />
      )}
    </div>
  );
}
