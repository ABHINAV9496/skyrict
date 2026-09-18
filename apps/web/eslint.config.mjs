import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    ignores: [
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
      // Generated Playwright artifacts (gitignored): report bundles are
      // minified and trip react-hooks rules.
      "playwright-report/**",
      "test-results/**",
      "blob-report/**",
      "playwright/.cache/**",
      // Playwright specs run in Node, not React; the fixture continuation
      // parameter is named `use`, which the react-hooks rule flags as a
      // forbidden Hook call. Type-checking (tsc) and runtime behavior
      // (Playwright) still cover these files.
      "e2e/**",
    ],
  },
];

export default eslintConfig;
