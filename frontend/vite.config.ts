/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: "react", test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 30 },
            { name: "msal", test: /node_modules[\\/]@azure[\\/]/, priority: 20 },
            { name: "recharts", test: /node_modules[\\/]recharts[\\/]/, priority: 10 },
            { name: "vendor", test: /node_modules[\\/]/, priority: 0 },
          ],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/mocked/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/mocked/setup.ts"],
    css: false,
  },
});
