/** @input Frontend unit files. @output Isolated unit-test collection. @position Test configuration. @doc-sync Update INDEX.md on changes. */
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { include: ["src/**/*.test.ts"] } });
