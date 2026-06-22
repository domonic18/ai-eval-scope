import js from '@eslint/js'
import globals from 'globals'
import tseslint from 'typescript-eslint'

// ESLint flat config（eslint 9+）— Node + Express + TypeScript（CommonJS）
export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'public', 'prisma/migrations', 'scf_bootstrap.js'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.node,
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
)
