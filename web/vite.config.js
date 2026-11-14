import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The page loads nothing from third parties: the kit's styles and fonts are
// bundled, and the app talks only to its own sidecar.
export default defineConfig({
  plugins: [svelte()],
  build: { outDir: "dist", emptyOutDir: true },
});
