// `npm run preview`: `next dev` with in-browser fixtures instead of Clerk and
// the backend, for working on the UI alone. Development only.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const next = require.resolve("next/dist/bin/next");

const child = spawn(process.execPath, [next, "dev", ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, NEXT_PUBLIC_CITESET_PREVIEW: "1" },
});
child.on("exit", (code) => process.exit(code ?? 0));
