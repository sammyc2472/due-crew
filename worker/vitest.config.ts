import path from "node:path";
import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig(async () => {
  const migrations = await readD1Migrations(path.join(import.meta.dirname, "migrations"));
  return {
    plugins: [
      cloudflareTest({
        wrangler: { configPath: "./wrangler.toml" },
        miniflare: { bindings: { TEST_MIGRATIONS: migrations, ADMIN_TOKEN: "test-admin", RESEND_API_KEY: "test-resend" } },
      }),
    ],
    // A test here is a run of real requests through workerd and D1 (some
    // send hundreds): about a second on a laptop, but a busy CI runner has
    // taken several times longer, past vitest's 5s default.
    test: { setupFiles: ["./test/setup.ts"], testTimeout: 30_000 },
  };
});
