import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  // Prevent Vite from clearing the terminal
  clearScreen: false,

  server: {
    // Tauri expects a fixed port
    port: 1420,
    strictPort: true,
    watch: {
      // Watch the Tauri source files for live reload in dev
      ignored: ["**/src-tauri/**"],
    },
  },

  // Allow VITE_ and TAURI_ env vars in client code
  envPrefix: ["VITE_", "TAURI_"],

  build: {
    // Tauri supports modern Chromium — target Chrome 105 for best compatibility
    target: process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome105" : "safari13",
    // Don't minify in debug builds
    minify: !process.env.TAURI_ENV_DEBUG ? "esbuild" : false,
    // Produce source maps in debug builds
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
  },
});
