import monosPreset from "@monos/ui/tailwind-preset";

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{svelte,js,ts}",
    // The kit's own components are class-driven, so their source has to be
    // scanned for the utilities they use.
    "./node_modules/@monos/ui/src/**/*.{svelte,js}",
  ],
  presets: [monosPreset],
  theme: {
    extend: {
      borderRadius: { ui: "var(--radius)" },
      fontFamily: { ui: "var(--font-ui)" },
    },
  },
  darkMode: "class",
};
