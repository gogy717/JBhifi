import { execFileSync } from "node:child_process";

import { stack } from "../playwright.config";

/**
 * Build the disposable database the browser suite runs against, once per `npm run test:e2e`.
 *
 * `--create` drops and rebuilds it from `sql/*.sql` and then adds the scenarios `doc/demo.md` documents:
 * the completed orders the return journeys use, the return waiting at the Melbourne Central desk, and the
 * deliberately empty `LG-43UT8050` at Sydney CBD. The seeder refuses a name that is not clearly
 * disposable, so a stray `POSTGRES_DB=jbhifi` cannot be dropped from here, and it runs before the tests —
 * the API server is started by the config but proves only that the process is up, so the database it
 * serves is this script's job.
 */
export default function globalSetup() {
  execFileSync(stack.python,
    ["scripts/seed_demo.py", "--database", stack.DATABASE, "--create", "--seed", "9120"],
    { cwd: stack.repoRoot, stdio: "inherit" });
}
