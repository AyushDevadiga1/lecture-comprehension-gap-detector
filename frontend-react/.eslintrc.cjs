/* ESLint 8 (eslintrc format). Kept as .cjs because package.json is "type": "module".
 *
 * Two rules in here exist to make plan/REACT_ARCHITECTURE.md enforceable rather
 * than aspirational. Without this file `npm run lint` exits non-zero ("couldn't
 * find a configuration file"), so both were documentation until now.
 */

/** @type {import('eslint').Linter.Config} */
module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['@typescript-eslint', 'react-hooks', 'react-refresh'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  settings: { react: { version: '18.3' } },
  ignorePatterns: ['dist', 'coverage', 'node_modules', 'e2e', '*.cjs'],
  rules: {
    // Fast Refresh needs a component-only module boundary; a store or a constant
    // exported next to a component makes HMR fall back to a full reload.
    'react-refresh/only-export-components': ['error', { allowConstantExport: true }],
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
    '@typescript-eslint/no-explicit-any': 'error',
    'no-console': ['error', { allow: ['warn', 'error'] }],
    eqeqeq: ['error', 'smart'],
    'prefer-const': 'error',
    'no-var': 'error',
  },
  overrides: [
    {
      // REACT_ARCHITECTURE §6: "no panel calls fetch" — one request path, so the
      // X-API-Key header, the {detail} extraction and the 401 banner exist once.
      // `api/` and `lib/` are the boundary; features/ and components/ consume them.
      files: ['src/features/**/*.{ts,tsx}', 'src/components/**/*.{ts,tsx}'],
      rules: {
        'no-restricted-globals': [
          'error',
          {
            name: 'fetch',
            message:
              'Panels must not call fetch. Use the wrapper in src/api/ — plan/REACT_ARCHITECTURE.md §6.',
          },
        ],
      },
    },
    {
      // Test files legitimately reach past the boundaries (to stub the transport,
      // to assert on headers) and allow `any` in fixtures.
      files: ['src/**/*.test.{ts,tsx}', 'src/test/**/*.{ts,tsx}'],
      rules: {
        '@typescript-eslint/no-explicit-any': 'off',
        'no-restricted-globals': 'off',
      },
    },
    {
      // REACT_ARCHITECTURE §4: "no module outside theme.ts may name a colour".
      // The ported token table lands in Wave 2; enabling the rule before then
      // would flag every hex in the current MUI theme. Enabled in that wave.
      files: ['src/**/*.{ts,tsx,css}'],
      excludedFiles: ['src/theme/**', 'src/index.css'],
      rules: {
        'no-restricted-syntax': 'off',
      },
    },
  ],
}
