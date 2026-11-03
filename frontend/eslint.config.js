import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'

export default [
  { ignores: ['dist', 'playwright-report', 'test-results'] },
  js.configs.recommended,
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: { ecmaVersion: 2023, sourceType: 'module', globals: { ...globals.browser, ...globals.vitest }, parserOptions: { ecmaFeatures: { jsx: true } } },
    plugins: { react, 'react-hooks': reactHooks },
    settings: { react: { version: '18.3' } },
    rules: { ...reactHooks.configs.recommended.rules, 'react/jsx-uses-vars': 'error', 'react/jsx-uses-react': 'off', 'no-unused-vars': ['error', { varsIgnorePattern: '^_' }] },
  },
]
