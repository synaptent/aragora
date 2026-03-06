/** @type {import('tailwindcss').Config} */
module.exports = {
  // v4 auto-detects content; safelist replaced by @source inline() in globals.css
  theme: {
    screens: {
      'xs': '320px',    // Mobile-first breakpoint
      'sm': '640px',
      'md': '768px',
      'lg': '1024px',
      'xl': '1280px',
      '2xl': '1536px',
    },
    extend: {
      fontFamily: {
        mono: [
          'JetBrains Mono',
          'Fira Code',
          'SF Mono',
          'Menlo',
          'Monaco',
          'Consolas',
          'Liberation Mono',
          'Courier New',
          'monospace',
        ],
      },
      colors: {
        // Base colors using CSS variables for theme support
        'bg': 'var(--bg)',
        'surface': 'var(--surface)',
        'surface-elevated': 'var(--surface-elevated)',
        'border': 'var(--border)',
        'text': 'var(--text)',
        'text-muted': 'var(--text-muted)',

        // Acid/Demoscene accent colors
        'acid-green': 'var(--acid-green)',
        'acid-cyan': 'var(--acid-cyan)',
        'acid-magenta': 'var(--acid-magenta)',
        'acid-yellow': 'var(--acid-yellow)',
        'matrix-green': 'var(--matrix-green)',
        'terminal-green': 'var(--terminal-green)',

        // Semantic colors
        'accent': 'var(--accent)',
        'accent-glow': 'var(--accent-glow)',
        'success': 'var(--success)',
        'warning': 'var(--warning)',

        // Agent colors
        'purple': 'var(--purple)',
        'gold': 'var(--gold)',
        'crimson': 'var(--crimson)',
        'cyan': 'var(--cyan)',
      },
      animation: {
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'acid-shift': 'acid-shift 4s ease infinite',
        'cursor-blink': 'cursor-blink 1s step-end infinite',
        'boot-line': 'boot-line 0.3s ease forwards',
        // Loading animation for debate progress bar
        'loading-bar': 'loading-bar 2s ease-in-out infinite',
        // Mobile accessibility animations
        'ripple': 'ripple 0.6s linear forwards',
        'slide-in-from-bottom': 'slide-in-from-bottom 0.3s ease-out',
        'slide-in-from-left': 'slide-in-from-left 0.3s ease-out',
        'slide-in-from-right': 'slide-in-from-right 0.3s ease-out',
        'fade-in': 'fade-in 0.2s ease-out',
      },
      keyframes: {
        'ripple': {
          'from': { transform: 'translate(-50%, -50%) scale(0)', opacity: '1' },
          'to': { transform: 'translate(-50%, -50%) scale(4)', opacity: '0' },
        },
        'slide-in-from-bottom': {
          'from': { transform: 'translateY(100%)' },
          'to': { transform: 'translateY(0)' },
        },
        'slide-in-from-left': {
          'from': { transform: 'translateX(-100%)' },
          'to': { transform: 'translateX(0)' },
        },
        'slide-in-from-right': {
          'from': { transform: 'translateX(100%)' },
          'to': { transform: 'translateX(0)' },
        },
        'fade-in': {
          'from': { opacity: '0' },
          'to': { opacity: '1' },
        },
        'loading-bar': {
          '0%': { width: '0%', marginLeft: '0%' },
          '50%': { width: '40%', marginLeft: '30%' },
          '100%': { width: '0%', marginLeft: '100%' },
        },
      },
      borderRadius: {
        'panel': 'var(--radius-md)',
      },
      boxShadow: {
        'glow': '0 0 20px var(--accent-glow)',
        'glow-lg': '0 0 30px var(--accent-glow)',
        'terminal': '0 0 10px var(--accent-glow), inset 0 0 10px var(--accent-glow)',
        'panel': 'var(--shadow-panel)',
        'elevated': 'var(--shadow-elevated)',
        'floating': 'var(--shadow-floating)',
      },
    },
  },
  plugins: [],
}
