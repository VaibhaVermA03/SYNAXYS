const token = (name) => `rgb(var(--${name}) / <alpha-value>)`

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'Geist Sans', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
        pixel: ['var(--font-pixel)'], // Geist Pixel Circle (see public/fonts/README.md)
      },
      colors: {
        bg: token('bg'), surface: token('surface'), 'surface-2': token('surface-2'), border: token('border'),
        fg: token('fg'), muted: token('muted'), accent: token('accent'), 'accent-fg': token('accent-fg'), 'accent-ink': token('accent-ink'),
        danger: token('danger'), 'danger-fg': token('danger-fg'), warn: token('warn'), ok: token('ok'),
      },
      keyframes: {
        float: { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-8px)' } },
        blob: {
          '0%,100%': { transform: 'translate(0,0) scale(1)' },
          '33%': { transform: 'translate(30px,-20px) scale(1.08)' },
          '66%': { transform: 'translate(-20px,20px) scale(0.95)' },
        },
        reveal: { from: { opacity: '0', transform: 'translateY(12px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        blink: { '0%,100%': { opacity: '1' }, '50%': { opacity: '0' } },
      },
      animation: {
        float: 'float 6s ease-in-out infinite',
        blob: 'blob 18s ease-in-out infinite',
        reveal: 'reveal 0.7s cubic-bezier(0.22,1,0.36,1) both',
        blink: 'blink 1s steps(2,start) infinite',
      },
    },
  },
  plugins: [],
}
