import { readFileSync } from "node:fs";
import { join } from "node:path";

import { REPO_ROOT } from "./contracts.js";

export interface Deployment {
  token0: string;
  token1: string;
  naiveAmm: string;
  shardedAmm: string;
}

/** Reads the deployed addresses straight out of forge's own broadcast record for
 * Deploy.s.sol, instead of hand-copying addresses after every deploy. */
export function loadDeployment(chainId: number): Deployment {
  const path = join(REPO_ROOT, "contracts", "broadcast", "Deploy.s.sol", String(chainId), "run-latest.json");
  const record = JSON.parse(readFileSync(path, "utf-8")) as {
    transactions: Array<{ contractName: string; contractAddress: string; transactionType: string }>;
  };

  const creates = record.transactions.filter((tx) => tx.transactionType === "CREATE");
  const byName = (name: string, occurrence = 0) =>
    creates.filter((tx) => tx.contractName === name)[occurrence]?.contractAddress;

  const token0 = byName("DemoToken", 0);
  const token1 = byName("DemoToken", 1);
  const naiveAmm = byName("NaiveAMM", 0);
  const shardedAmm = byName("ShardedAMM", 0);

  if (!token0 || !token1 || !naiveAmm || !shardedAmm) {
    throw new Error(`Incomplete deployment record at ${path}`);
  }

  return { token0, token1, naiveAmm, shardedAmm };
}
