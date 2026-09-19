#!/usr/bin/env -S npx tsx
/**
 * ParaCheck CLI.
 *
 *   paracheck analyze
 *     Runs the Python static analyzer against NaiveAMM and ShardedAMM, writes
 *     demo-page/reports/static-naive.json and static-sharded.json.
 *
 *   paracheck loadtest --chain-id <id> [--traders N] [--bands N] [--band-width WEI]
 *     Fires concurrent swaps against both deployed AMMs (addresses read from the
 *     matching contracts/broadcast/Deploy.s.sol/<chainId>/run-latest.json), traces the
 *     block(s), and writes demo-page/reports/dynamic-comparison.json.
 *     RPC_URL (or DYNAMIC_RPC_URL if set) must support debug_traceBlockByNumber.
 *
 *   paracheck livetx --contract naive|sharded --amount WEI
 *     Sends one real swap from LIVETX_PRIVATE_KEY against a deployed AMM, polls for the
 *     receipt, and prints the Monadscan link. This is the live-transaction demo trigger.
 */
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { Contract, JsonRpcProvider, Wallet, parseUnits } from "ethers";

import { countConflicts, type ConflictReport } from "./dynamic/conflict_counter.js";
import { loadAbi, REPO_ROOT } from "./dynamic/contracts.js";
import { loadDeployment } from "./dynamic/deployment.js";
import { PRESTATE_DIFF_TRACER, RpcClient } from "./dynamic/rpc_client.js";
import { extractBlockWriteSets, filterToAddress } from "./dynamic/trace_diff.js";
import { withRetry } from "./dynamic/retry.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPORTS_DIR = join(REPO_ROOT, "demo-page", "reports");

function parseArgs(argv: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg.startsWith("--")) {
      const key = arg.slice(2);
      const value = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
      out[key] = value;
    }
  }
  return out;
}

function monadscanTxUrl(chainId: number, txHash: string): string {
  const base = chainId === 143 ? "https://monadscan.com" : "https://testnet.monadscan.com";
  return `${base}/tx/${txHash}`;
}

function monadscanAddressUrl(chainId: number, address: string): string {
  const base = chainId === 143 ? "https://monadscan.com" : "https://testnet.monadscan.com";
  return `${base}/address/${address}`;
}

// ---------------------------------------------------------------------------
// analyze
// ---------------------------------------------------------------------------

function runAnalyze(): void {
  mkdirSync(REPORTS_DIR, { recursive: true });
  const contractsDir = join(REPO_ROOT, "contracts");
  const staticDir = join(REPO_ROOT, "analyzer", "static");
  const python = join(REPO_ROOT, "analyzer", ".venv", "bin", "python3");

  const targets: Array<[string, string]> = [
    ["NaiveAMM", join(contractsDir, "src", "NaiveAMM.sol")],
    ["ShardedAMM", join(contractsDir, "src", "ShardedAMM.sol")],
  ];

  for (const [name, sourceFile] of targets) {
    const outFile = join(REPORTS_DIR, `static-${name.toLowerCase()}.json`);
    const result = spawnSync(
      python,
      ["report.py", contractsDir, name, sourceFile, "--out", outFile],
      { cwd: staticDir, stdio: "inherit" },
    );
    if (result.status !== 0) {
      throw new Error(`static analyzer failed for ${name} (exit ${result.status})`);
    }
    console.log(`wrote ${outFile}`);
  }
}

// ---------------------------------------------------------------------------
// loadtest
// ---------------------------------------------------------------------------

const nonceCache = new Map<string, number>();
async function nextNonce(provider: JsonRpcProvider, address: string): Promise<number> {
  if (!nonceCache.has(address)) {
    nonceCache.set(address, await provider.getTransactionCount(address, "latest"));
  }
  const n = nonceCache.get(address)!;
  nonceCache.set(address, n + 1);
  return n;
}

async function fundAndApprove(
  provider: JsonRpcProvider,
  wallet: Wallet,
  tokenAbi: any[],
  tokenAddr: string,
  ammAddr: string,
  amount: bigint,
) {
  const token = new Contract(tokenAddr, tokenAbi, wallet);
  const mintTx = await token.mint(wallet.address, amount, { nonce: await nextNonce(provider, wallet.address) });
  await withRetry(() => mintTx.wait());
  const approveTx = await token.approve(ammAddr, amount, { nonce: await nextNonce(provider, wallet.address) });
  await withRetry(() => approveTx.wait());
}

function sumReports(reports: ConflictReport[]): ConflictReport {
  return reports.reduce(
    (acc, r) => ({
      totalTransactions: acc.totalTransactions + r.totalTransactions,
      conflictingSlots: acc.conflictingSlots + r.conflictingSlots,
      conflictingTransactionPairs: acc.conflictingTransactionPairs + r.conflictingTransactionPairs,
      transactionsInvolvedInConflict: acc.transactionsInvolvedInConflict + r.transactionsInvolvedInConflict,
      slotWriterCounts: { ...acc.slotWriterCounts, ...r.slotWriterCounts },
    }),
    { totalTransactions: 0, conflictingSlots: 0, conflictingTransactionPairs: 0, transactionsInvolvedInConflict: 0, slotWriterCounts: {} },
  );
}

async function fireConcurrentSwaps(
  provider: JsonRpcProvider,
  rpcClient: RpcClient,
  ammAddr: string,
  ammAbi: any[],
  tokenInAddr: string,
  swaps: Array<{ wallet: Wallet; amountIn: bigint }>,
) {
  await provider.send("evm_setAutomine", [false]).catch(() => {
    // real networks don't support this - swaps will simply land across whatever
    // blocks the network naturally produces, and we trace each block that has one.
  });

  // Pre-fetch nonces, then fire every send together instead of sequentially - on a live
  // network, sequential sends (each with its own RPC round trip) can easily straddle
  // multiple ~300-600ms blocks, when the whole point is to land these in the same
  // window if at all possible.
  const nonces = await Promise.all(swaps.map(({ wallet }) => nextNonce(provider, wallet.address)));
  const pending = await Promise.all(
    swaps.map(({ wallet, amountIn }, i) => {
      const amm = new Contract(ammAddr, ammAbi, wallet);
      return amm.swap(tokenInAddr, amountIn, 0, { nonce: nonces[i], gasLimit: 500_000n });
    }),
  );

  await provider.send("evm_mine", []).catch(() => {});
  await provider.send("evm_setAutomine", [true]).catch(() => {});

  // Sequential, retrying waits: polling several receipts in parallel is what triggered
  // QuickNode's per-second rate limit in practice - trading a little wall-clock time for
  // staying under it is worth it here.
  const receipts: Array<{ blockNumber: number }> = [];
  for (const tx of pending) {
    receipts.push((await withRetry(() => tx.wait()))!);
  }
  const blockNumbers = [...new Set(receipts.map((r) => r.blockNumber as number))];

  // Conflicts only mean something *within* one block - transactions in different blocks
  // never execute in parallel with each other, so their write-sets must never be merged
  // together (txIndex is only unique within a single block's trace). Trace and count
  // each block separately, then sum the per-block reports.
  const fullReports: ConflictReport[] = [];
  const ammReports: ConflictReport[] = [];
  for (const blockNumber of blockNumbers) {
    const trace = await withRetry(() => rpcClient.traceBlockByNumber(blockNumber, PRESTATE_DIFF_TRACER));
    const writeSets = extractBlockWriteSets(trace as Array<{ txHash?: string; result: any }>);
    fullReports.push(countConflicts(writeSets));
    ammReports.push(countConflicts(filterToAddress(writeSets, ammAddr)));
  }

  return {
    blockNumbers,
    fullReport: sumReports(fullReports),
    ammReport: sumReports(ammReports),
  };
}

async function runLoadtest(args: Record<string, string>): Promise<void> {
  const rpcUrl = process.env.DYNAMIC_RPC_URL || process.env.RPC_URL;
  if (!rpcUrl) throw new Error("Set DYNAMIC_RPC_URL (or RPC_URL) to an endpoint with debug_* support");

  const chainId = Number(args["chain-id"] ?? process.env.CHAIN_ID ?? 10143);
  const traderCount = Number(args["traders"] ?? 5);
  const bandCount = Number(args["bands"] ?? 3);
  const bandWidth = parseUnits(args["band-width"] ?? "1000", 18);

  const privateKeysEnv = process.env.LOADTEST_PRIVATE_KEYS;
  if (!privateKeysEnv) {
    throw new Error("Set LOADTEST_PRIVATE_KEYS to a comma-separated list of funded testnet private keys");
  }
  const privateKeys = privateKeysEnv.split(",").map((s) => s.trim());
  if (privateKeys.length < Math.max(traderCount, bandCount)) {
    throw new Error(`Need at least ${Math.max(traderCount, bandCount)} private keys in LOADTEST_PRIVATE_KEYS`);
  }

  const provider = new JsonRpcProvider(rpcUrl);
  provider.pollingInterval = 2000; // avoid tripping QuickNode's per-second rate limit
  const rpcClient = new RpcClient(rpcUrl);
  const deployment = loadDeployment(chainId);

  const tokenAbi = loadAbi("DemoToken");
  const ammAbi = loadAbi("NaiveAMM");

  const wallets = privateKeys.map((pk) => new Wallet(pk, provider));
  const seedAmount = parseUnits("10000000", 18);

  for (const wallet of wallets.slice(0, Math.max(traderCount, bandCount))) {
    await fundAndApprove(provider, wallet, tokenAbi, deployment.token0, deployment.naiveAmm, seedAmount);
    await fundAndApprove(provider, wallet, tokenAbi, deployment.token0, deployment.shardedAmm, seedAmount);
  }

  console.log(`Firing ${traderCount} concurrent NaiveAMM swaps...`);
  const naive = await fireConcurrentSwaps(
    provider,
    rpcClient,
    deployment.naiveAmm,
    ammAbi,
    deployment.token0,
    wallets.slice(0, traderCount).map((wallet) => ({ wallet, amountIn: parseUnits("100", 18) })),
  );

  console.log(`Firing ${bandCount} concurrent ShardedAMM swaps (one per band)...`);
  const sharded = await fireConcurrentSwaps(
    provider,
    rpcClient,
    deployment.shardedAmm,
    ammAbi,
    deployment.token0,
    wallets.slice(0, bandCount).map((wallet, band) => ({
      wallet,
      amountIn: parseUnits("100", 18) + bandWidth * BigInt(band),
    })),
  );

  const report = {
    chainId,
    generatedAt: new Date().toISOString(),
    naiveAMM: { address: deployment.naiveAmm, ...naive },
    shardedAMM: { address: deployment.shardedAmm, bandCount, ...sharded },
  };

  mkdirSync(REPORTS_DIR, { recursive: true });
  const outFile = join(REPORTS_DIR, "dynamic-comparison.json");
  writeFileSync(outFile, JSON.stringify(report, (_k, v) => (typeof v === "bigint" ? v.toString() : v), 2) + "\n");
  console.log(`wrote ${outFile}`);
}

// ---------------------------------------------------------------------------
// livetx
// ---------------------------------------------------------------------------

async function runLivetx(args: Record<string, string>): Promise<void> {
  const rpcUrl = process.env.RPC_URL;
  const privateKey = process.env.LIVETX_PRIVATE_KEY;
  if (!rpcUrl) throw new Error("Set RPC_URL");
  if (!privateKey) throw new Error("Set LIVETX_PRIVATE_KEY (a funded demo wallet, separate from load-test wallets)");

  const chainId = Number(args["chain-id"] ?? process.env.CHAIN_ID ?? 10143);
  const which = args["contract"] === "sharded" ? "shardedAmm" : "naiveAmm";
  const amountIn = parseUnits(args["amount"] ?? "10", 18);

  const provider = new JsonRpcProvider(rpcUrl);
  provider.pollingInterval = 1000;
  const wallet = new Wallet(privateKey, provider);
  const deployment = loadDeployment(chainId);
  const ammAddr = deployment[which];

  const ammAbi = loadAbi("NaiveAMM");
  const tokenAbi = loadAbi("DemoToken");
  const amm = new Contract(ammAddr, ammAbi, wallet);
  const token0 = new Contract(deployment.token0, tokenAbi, wallet);

  const balance = await token0.balanceOf(wallet.address);
  if (balance < amountIn) {
    console.log(`Minting ${args["amount"] ?? "10"} token0 to ${wallet.address} (DemoToken.mint is unrestricted)...`);
    const nonce = await nextNonce(provider, wallet.address);
    await (await token0.mint(wallet.address, amountIn, { nonce })).wait();
  }

  const allowance = await token0.allowance(wallet.address, ammAddr);
  if (allowance < amountIn) {
    console.log("Approving AMM to spend token0...");
    const nonce = await nextNonce(provider, wallet.address);
    await (await token0.approve(ammAddr, amountIn, { nonce })).wait();
  }

  console.log(`Sending live swap: ${wallet.address} -> ${ammAddr} (amountIn=${amountIn})`);
  const swapNonce = await nextNonce(provider, wallet.address);
  const tx = await amm.swap(deployment.token0, amountIn, 0, { nonce: swapNonce, gasLimit: 500_000n });
  console.log(`tx sent: ${tx.hash}`);
  console.log(monadscanTxUrl(chainId, tx.hash));

  const receipt = await tx.wait();
  console.log(`confirmed in block ${receipt.blockNumber} (status=${receipt.status})`);

  console.log(
    JSON.stringify(
      {
        txHash: tx.hash,
        monadscanUrl: monadscanTxUrl(chainId, tx.hash),
        blockNumber: receipt.blockNumber,
        status: receipt.status,
        contract: ammAddr,
        contractUrl: monadscanAddressUrl(chainId, ammAddr),
      },
      null,
      2,
    ),
  );
}

// ---------------------------------------------------------------------------
// deployment-info
// ---------------------------------------------------------------------------

function runDeploymentInfo(args: Record<string, string>): void {
  const chainId = Number(args["chain-id"] ?? process.env.CHAIN_ID ?? 10143);
  const deployment = loadDeployment(chainId);

  const info = {
    chainId,
    naiveAMM: { address: deployment.naiveAmm, monadscanUrl: monadscanAddressUrl(chainId, deployment.naiveAmm) },
    shardedAMM: { address: deployment.shardedAmm, monadscanUrl: monadscanAddressUrl(chainId, deployment.shardedAmm) },
    token0: { address: deployment.token0, monadscanUrl: monadscanAddressUrl(chainId, deployment.token0) },
    token1: { address: deployment.token1, monadscanUrl: monadscanAddressUrl(chainId, deployment.token1) },
  };

  mkdirSync(REPORTS_DIR, { recursive: true });
  const outFile = join(REPORTS_DIR, "deployment.json");
  writeFileSync(outFile, JSON.stringify(info, null, 2) + "\n");
  console.log(`wrote ${outFile}`);
}

// ---------------------------------------------------------------------------

async function main() {
  const [, , command, ...rest] = process.argv;
  const args = parseArgs(rest);

  switch (command) {
    case "analyze":
      runAnalyze();
      break;
    case "loadtest":
      await runLoadtest(args);
      break;
    case "livetx":
      await runLivetx(args);
      break;
    case "deployment-info":
      runDeploymentInfo(args);
      break;
    default:
      console.error("Usage: paracheck <analyze|loadtest|livetx|deployment-info> [options]");
      process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
