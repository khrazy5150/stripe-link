// Why this exists: `Products.vue` called `productStore.fetchFull(row)` while declaring
// `const store = useProductsStore()`. Editing ANY product failed with "productStore is not defined".
// Shipped 2026-09-01, reported 2026-09-10 — nine days, because nothing could catch it. Vite does not
// resolve identifiers inside a function body, so the build succeeded; the error existed only when the
// handler ran, and no test exercises the dashboard's JavaScript.
//
// `no-undef` is the rule that exists precisely for that, and it had never run against this codebase.
//
// Deliberately NOT a style config. Formatting rules on an existing codebase produce hundreds of
// findings, which trains everyone to ignore the output — and the output is the whole point. This turns
// on the rules that catch REAL errors and leaves taste alone.
import js from "@eslint/js";
import vue from "eslint-plugin-vue";
import globals from "globals";

export default [
  { ignores: ["dist/**", "node_modules/**", "public/**"] },

  js.configs.recommended,
  ...vue.configs["flat/essential"],

  {
    files: ["**/*.js", "**/*.vue"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...globals.browser, ...globals.es2021 },
    },
    rules: {
      // ERROR, and it gates the build. Measured on the first run: ZERO findings across the whole
      // dashboard, so turning it into a blocker costs nothing today and catches the next one the day it
      // is typed rather than nine days later.
      "no-undef": "error",

      // Clean today too, and each is a real mistake rather than a preference.
      "vue/no-unused-components": "error",
      "vue/require-v-for-key": "error",
      "vue/no-use-v-if-with-v-for": "error",

      // WARN, not error, and the difference is deliberate. The first run found 41 unused names and 46
      // prop mutations in code that has been shipping for months. As errors they would fail the build on
      // day one, which means someone turns the linter off -- and then it catches nothing at all. As
      // warnings they are visible, countable, and fixable as they are touched, while `no-undef` still
      // blocks the thing that actually breaks the product.
      "no-unused-vars": ["warn", {
        args: "none",
        varsIgnorePattern: "^_",
        caughtErrors: "none",
      }],
      // A child writing to its parent's prop: real Vue anti-pattern, 46 instances, and unpicking them is
      // a refactor rather than a lint fix.
      "vue/no-mutating-props": "warn",

      // Off on purpose: this codebase uses single-word component names deliberately (Orders.vue,
      // Shipping.vue), and renaming 40 files teaches nobody anything.
      "vue/multi-word-component-names": "off",
    },
  },
];
