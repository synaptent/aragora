/**
 * Design Tokens for Aragora
 *
 * Centralized design system tokens for colors, spacing, typography, and more.
 * These tokens are the source of truth and should be used throughout the app.
 */

export const colors = {
  accent: {
    DEFAULT: '#39ff14',
    hover: '#32e612',
    muted: 'rgba(57, 255, 20, 0.3)',
    subtle: 'rgba(57, 255, 20, 0.1)',
  },
  cyan: { DEFAULT: '#00ffff', hover: '#00e6e6', muted: 'rgba(0, 255, 255, 0.3)' },
  success: '#10b981',
  warning: '#f59e0b',
  error: '#ef4444',
  info: '#3b82f6',
  bg: { DEFAULT: '#0a0a0a', elevated: '#0d0d0d', overlay: '#141414' },
  border: { DEFAULT: '#1a1a1a', hover: '#2a2a2a', active: 'rgba(57, 255, 20, 0.3)' },
  text: { DEFAULT: '#e0e0e0', muted: '#9a9a9a', disabled: '#666666' },
  agents: {
    claude: '#00ffff',
    gpt4: '#10b981',
    gemini: '#a855f7',
    grok: '#ef4444',
    mistral: '#f59e0b',
    default: '#6b7280',
  },
} as const;

export const spacing = {
  xs: '4px',
  sm: '8px',
  md: '12px',
  lg: '16px',
  xl: '24px',
  '2xl': '32px',
} as const;

export const typography = {
  fontSize: { xs: '10px', sm: '12px', base: '14px', lg: '16px', xl: '20px', '2xl': '24px' },
  fontWeight: { normal: 400, medium: 500, semibold: 600, bold: 700 },
} as const;

export const radii = { sm: '4px', md: '8px', lg: '12px', full: '9999px' } as const;

export const shadows = {
  sm: '0 1px 2px rgba(0,0,0,0.3)',
  md: '0 4px 6px rgba(0,0,0,0.4)',
  glow: '0 0 10px var(--accent-glow)',
} as const;

export const tokens = { colors, spacing, typography, radii, shadows } as const;

export function getAgentColor(agent: string): string {
  const key = agent.toLowerCase().replace(/[^a-z0-9]/g, '') as keyof typeof colors.agents;
  return colors.agents[key] || colors.agents.default;
}

export default tokens;
