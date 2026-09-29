const SENSITIVE_KEY = /email|password|token|secret|authorization|cookie|apikey/i;

function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (value === null || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => !SENSITIVE_KEY.test(key))
      .map(([key, entry]) => [key, redact(entry)]),
  );
}

export async function capture(event: string, props: Record<string, unknown> = {}): Promise<void> {
  if (!process.env.NEXT_PUBLIC_POSTHOG_KEY) return;
  try {
    const safeProps = redact(props) as Record<string, unknown>;
    const { default: posthog } = await import('posthog-js');
    posthog.capture(event, safeProps);
  } catch {
    // Analytics is best-effort and must not break a user action.
  }
}
