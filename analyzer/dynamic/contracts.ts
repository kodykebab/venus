import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = join(__dirname, "..", "..");
export const CONTRACTS_OUT = join(REPO_ROOT, "contracts", "out");

/** Reads a contract's ABI from Foundry's build output - kept in sync automatically by
 * `forge build`, instead of hand-maintaining a duplicate ABI fragment here. */
export function loadAbi(contractName: string): any[] {
  const artifactPath = join(CONTRACTS_OUT, `${contractName}.sol`, `${contractName}.json`);
  const artifact = JSON.parse(readFileSync(artifactPath, "utf-8"));
  return artifact.abi;
}
