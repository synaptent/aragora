// Keep literal env reads so Next can inline these public, build-time switches.
// Opt-outs default off, preserving the existing streaming and audience behavior.
export const flags = {
  disableStreaming: process.env.NEXT_PUBLIC_FLAG_DISABLE_STREAMING === 'true',
  disableAudience: process.env.NEXT_PUBLIC_FLAG_DISABLE_AUDIENCE === 'true',
} as const;
