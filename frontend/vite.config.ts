/** @input Vite. @output Development proxy. @position Build. @doc-sync Update INDEX.md on changes. */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8010" } },
});
