import { defineConfig } from "@playwright/test";

// Demo insurance: clicks through the live demo against `make dev` (gate :8000, pay :8001, web :5173).
export default defineConfig({
  testDir: "e2e",
  timeout: 180_000,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    viewport: { width: 1366, height: 768 }, // the projector the demo targets
    screenshot: "only-on-failure",
  },
});
