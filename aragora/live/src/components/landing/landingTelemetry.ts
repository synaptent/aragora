type LandingTelemetryValue = string | number | boolean | null;

export type LandingTelemetryEvent =
  | 'preflight_shown'
  | 'preflight_selected'
  | 'preview_rendered'
  | 'preview_timeout'
  | 'preview_clarification_requested'
  | 'retry_clicked'
  | 'wrong_answer_clicked'
  | 'open_full_debate_clicked'
  | 'share_clicked';

export interface LandingFeedbackPayload {
  question?: string | null;
  interpreted_question?: string | null;
  final_answer?: string | null;
  result_warning?: string | null;
  result_mode?: string | null;
  debate_id?: string | null;
  verdict?: string | null;
  participant_count?: number | null;
  rewritten?: boolean | null;
}

function sanitizePayload(
  data: Record<string, LandingTelemetryValue | undefined>,
): Record<string, LandingTelemetryValue> {
  const cleaned: Record<string, LandingTelemetryValue> = {};

  for (const [key, value] of Object.entries(data)) {
    if (value === undefined) continue;
    if (typeof value === 'string') {
      cleaned[key] = value.slice(0, 160);
      continue;
    }
    cleaned[key] = value;
  }

  return cleaned;
}

export function trackLandingEvent(
  apiBase: string,
  eventType: LandingTelemetryEvent,
  data: Record<string, LandingTelemetryValue | undefined> = {},
): void {
  const payload = { event_type: eventType, data: sanitizePayload(data) };

  void fetch(`${apiBase.replace(/\/$/, '')}/api/v1/playground/landing/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => undefined);
}

export function submitLandingFeedback(apiBase: string, payload: LandingFeedbackPayload): void {
  const cleaned: Record<string, LandingTelemetryValue> = {};

  for (const [key, value] of Object.entries(payload)) {
    if (value === undefined) continue;
    if (typeof value === 'string') {
      cleaned[key] = value.slice(0, 1600);
      continue;
    }
    cleaned[key] = value;
  }

  void fetch(`${apiBase.replace(/\/$/, '')}/api/v1/playground/landing/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cleaned),
    keepalive: true,
  }).catch(() => undefined);
}
