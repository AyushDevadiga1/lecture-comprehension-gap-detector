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
      // `src/theme/**` holds the tokens and is exempt; everything else must ask
      // for one -- a MUI slot (`primary.main`), a custom property
      // (`var(--lgc-*)`), or `tint()` from `src/theme/alpha`.
      //
      // The `(?<!&)` lookbehind keeps a hex inside an HTML entity from
      // counting, and `{3,8}` covers #abc, #aabbcc and the 4/8-digit forms.
      // Enabled with the ported token table; `src/theme/scan.test.ts` is the
      // runtime twin, so a file added outside ESLint is still caught.
      //
      // The hex half of this rule used to be the *whole* rule, which made it a
      // guard against a notation rather than against colours — and 16 rgba()
      // literals sat in Navbar, ErrorAlert, FacultyDashboard and
      // StudentDashboard while `npm run lint` stayed green. `theme/alpha.ts`
      // had already said in a docstring that "rgba(255,255,255,0.06) is a named
      // colour just as much as a hex", so the CSS colour *functions* are now
      // matched too. Two of those literals were live bugs: a white wash is
      // invisible in light mode, and #6366f1 is the off-palette indigo
      // `muiTheme.ts` documents having deleted.
      files: ['src/**/*.{ts,tsx}'],
      excludedFiles: ['src/theme/**'],
      rules: {
        'no-restricted-syntax': [
          'error',
          {
            // esquery, not a bare regex: `no-restricted-syntax` selectors are
            // AST patterns. A colour almost always sits *inside* a longer string
            // (`color: '#fff'`), so the attribute value is matched as a
            // substring. `Literal` covers plain strings and JSX attributes;
            // `TemplateElement` covers a colour inside a template literal.
            //
            // Hex first, then every CSS colour function. No commas inside the
            // alternation: a top-level comma separates esquery selectors, and
            // one inside the regex would be ambiguous to parse.
            //
            // Named keywords (`white`, `red`) are deliberately NOT matched. They
            // are too easy to hit in prose, fixture data and test descriptions
            // to be worth the false positives; `transparent`, `inherit` and
            // `currentColor` are not palette values anyway.
            selector: [
              "Literal[value=/(?<!&)#[0-9a-fA-F]{3,8}/]",
              'TemplateElement[value=/(?<!&)#[0-9a-fA-F]{3,8}/]',
              'Literal[value=/\\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix|light-dark)\\s*\\(/]',
              'TemplateElement[value=/\\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix|light-dark)\\s*\\(/]',
            ].join(', '),
            message:
              'Colours belong in src/theme/. Use a token: primary.main, var(--lgc-*), or tint() from src/theme/alpha. See plan/REACT_ARCHITECTURE.md §4.',
          },
        ],
      },
    },
  ],
}
