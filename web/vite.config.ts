/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    // Inside the Python package, not "dist", which collides with PyInstaller's folder (§17).
    // Relative to web/, so no Node types are needed to type-check this file.
    outDir: "../src/mihenk/web_dist",
    emptyOutDir: true,
  },
  test: { environment: "jsdom", globals: true },
});
