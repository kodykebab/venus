#!/usr/bin/env node
/**
 * Checks that the deployed D1 database matches schema.sql.
 *
 * This exists because applying the schema does not guarantee it took. Every
 * statement in schema.sql is `CREATE TABLE IF NOT EXISTS`, which is exactly as
 * quiet when the existing table is wrong as when it is right - the database
 * kept an earlier scaffold's `accounts` table across several deploys and
 * nothing said so until a request failed on a missing column.
 *
 * It also runs `PRAGMA foreign_key_check`, which catches the other half of that
 * incident: renaming a table rewrites the foreign keys that reference it, so
 * `ALTER TABLE accounts RENAME TO accounts_old` silently repointed
 * `installations.account_id` at a table with no `id` column. Every insert into
 * installations then failed with "foreign key mismatch", which surfaced to a
 * user as a 500 from the install callback.
 *
 * Usage: node scripts/verify-schema.mjs [--local]
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const remote = process.argv.includes("--local") ? "--local" : "--remote";

function query(sql) {
  const out = execFileSync(
    "npx",
    ["wrangler", "d1", "execute", "paracheck", remote, "--command", sql, "--json", "-y"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
  // wrangler prints a banner before the JSON.
  const start = out.indexOf("[");
  return JSON.parse(out.slice(start))[0].results ?? [];
}

/** Table and column names schema.sql declares, without executing it. */
function expectedFromSchema() {
  const sql = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
  const expected = new Map();
  for (const match of sql.matchAll(
    /CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\(([\s\S]*?)\n\);/g,
  )) {
    const [, table, body] = match;
    const columns = body
      .split("\n")
      .map((line) => line.replace(/--.*$/, "").trim())
      .filter((line) => line && !/^(PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT)\b/i.test(line))
      .map((line) => line.split(/\s+/)[0])
      .filter(Boolean);
    expected.set(table, columns);
  }
  return expected;
}

const problems = [];
const expected = expectedFromSchema();

const live = new Set(
  query(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_cf%' AND name NOT LIKE 'sqlite_%'",
  ).map((row) => row.name),
);

for (const [table, columns] of expected) {
  if (!live.has(table)) {
    problems.push(`${table}: missing from the database`);
    continue;
  }
  const actual = new Set(query(`PRAGMA table_info(${table})`).map((c) => c.name));
  const absent = columns.filter((c) => !actual.has(c));
  if (absent.length) {
    problems.push(`${table}: missing column(s) ${absent.join(", ")}`);
  }
}

// Tables nobody declared: usually a rename artefact left behind, which is
// harmless until one of them still holds a foreign key.
for (const table of live) {
  if (!expected.has(table)) problems.push(`${table}: present but not in schema.sql`);
}

try {
  const violations = query("PRAGMA foreign_key_check");
  if (violations.length) {
    problems.push(`foreign_key_check: ${violations.length} violation(s)`);
  }
} catch (error) {
  // A mismatch makes the pragma itself error rather than return rows.
  problems.push(`foreign_key_check failed: ${String(error).split("\n").find((l) => l.includes("mismatch")) ?? "see output"}`);
}

if (problems.length) {
  console.error("Schema does not match schema.sql:\n");
  for (const problem of problems) console.error(`  ✗ ${problem}`);
  console.error(
    "\nTo replace a diverged table, rename it and re-apply the schema - then run\n" +
      "this again, because renaming rewrites foreign keys that pointed at it.",
  );
  process.exit(1);
}

console.log(`Schema matches schema.sql (${expected.size} tables, no FK violations).`);
