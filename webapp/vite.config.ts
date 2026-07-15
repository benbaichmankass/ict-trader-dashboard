import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// GitHub Pages serves this repo at https://<owner>.github.io/ict-trader-dashboard/,
// so every asset URL must be prefixed with the repo name. Overridable via
// VITE_BASE for a custom-domain / root deploy.
const base = process.env.VITE_BASE ?? "/ict-trader-dashboard/";

export default defineConfig({
  base,
  plugins: [svelte()],
  build: {
    target: "es2022",
    sourcemap: false,
  },
});
