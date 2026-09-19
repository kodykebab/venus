/**
 * Local correctness check for the dynamic analyzer (build order step 3): fires
 * concurrent swaps against NaiveAMM and ShardedAMM on local anvil, batches them into a
 * single block (automine off + one manual evm_mine), traces that block with
 * debug_traceBlockByNumber + prestateTracer/diffMode, and asserts:
 *   - NaiveAMM: every swap collides on the shared reserve0/reserve1 slots.
 *   - ShardedAMM: swaps spread one-per-band collide on nothing.
 *
 * Requires: anvil running locally (`anvil --network monad`) with Deploy.s.sol already
 * broadcast against it (see contracts/broadcast/Deploy.s.sol/<chainId>/run-latest.json).
 */
import { Contract, JsonRpcProvider, Wallet, parseUnits } from "ethers";

import { countConflicts } from "./conflict_counter.js";
import { loadAbi } from "./contracts.js";
import { loadDeployment } from "./deployment.js";
import { PRESTATE_DIFF_TRACER, RpcClient } from "./rpc_client.js";
import { extractBlockWriteSets, filterToAddress } from "./trace_diff.js";

const RPC_URL = process.env.RPC_URL ?? "http://127.0.0.1:8545";
const CHAIN_ID = Number(process.env.CHAIN_ID ?? 31337);
const BAND_COUNT = 3;
const BAND_WIDTH = parseUnits("1000", 18);

// anvil's well-known default dev account private keys.
const ANVIL_PRIVATE_KEYS = [
  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
  "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
  "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
  "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
  "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",
];

// ethers v6's default per-call "pending" nonce lookup can return a stale value when
// several transactions are sent back-to-back for the same account faster than the node
// round-trips each one - track nonces ourselves instead of relying on it.
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
  await (await token.mint(wallet.address, amount, { nonce: await nextNonce(provider, wallet.address) })).wait();
  await (await token.approve(ammAddr, amount, { nonce: await nextNonce(provider, wallet.address) })).wait();
}

async function fireConcurrentSwaps(
  provider: JsonRpcProvider,
  rpcClient: RpcClient,
  ammAddr: string,
  ammAbi: any[],
  tokenInAddr: string,
  swaps: Array<{ wallet: Wallet; amountIn: bigint }>,
) {
  await provider.send("evm_setAutomine", [false]);

  const pending = [];
  for (const { wallet, amountIn } of swaps) {
    const amm = new Contract(ammAddr, ammAbi, wallet);
    const nonce = await nextNonce(provider, wallet.address);
    // Skip eth_estimateGas: with automine off, estimating against a queue of other
    // pending swaps is unreliable on anvil. A fixed limit comfortably above the
    // ~300k gas a swap() actually uses (per the Foundry test suite) avoids that.
    pending.push(await amm.swap(tokenInAddr, amountIn, 0, { nonce, gasLimit: 500_000n }));
  }

  await provider.send("evm_mine", []);
  await provider.send("evm_setAutomine", [true]);

  const receipts = await Promise.all(pending.map((tx) => tx.wait()));
  const blockNumber = receipts[0].blockNumber as number;
  for (const r of receipts) {
    if (r.blockNumber !== blockNumber) {
      throw new Error("Swaps landed in different blocks - conflict window assumption broken");
    }
  }

  const trace = await rpcClient.traceBlockByNumber(blockNumber, PRESTATE_DIFF_TRACER);
  const writeSets = extractBlockWriteSets(trace as Array<{ txHash?: string; result: any }>);
  return {
    blockNumber,
    // Full report: every slot touched, including the ERC20 token contracts' own
    // balanceOf(AMM) accounting - always conflicts regardless of AMM-side sharding.
    fullReport: countConflicts(writeSets),
    // AMM-scoped report: only the target contract's own storage - this is what the
    // static analyzer evaluates too, so it's the apples-to-apples comparison.
    ammReport: countConflicts(filterToAddress(writeSets, ammAddr)),
  };
}

async function main() {
  const provider = new JsonRpcProvider(RPC_URL);
  const rpcClient = new RpcClient(RPC_URL);
  const deployment = loadDeployment(CHAIN_ID);

  const tokenAbi = loadAbi("DemoToken");
  const ammAbi = loadAbi("NaiveAMM"); // NaiveAMM/ShardedAMM share the IAMM surface

  const wallets = ANVIL_PRIVATE_KEYS.map((pk) => new Wallet(pk, provider));
  const seedAmount = parseUnits("10000000", 18);

  for (const wallet of wallets) {
    await fundAndApprove(provider, wallet, tokenAbi, deployment.token0, deployment.naiveAmm, seedAmount);
    await fundAndApprove(provider, wallet, tokenAbi, deployment.token0, deployment.shardedAmm, seedAmount);
  }

  console.log(`Firing ${wallets.length} concurrent NaiveAMM swaps (same amount, same slots)...`);
  const naive = await fireConcurrentSwaps(
    provider,
    rpcClient,
    deployment.naiveAmm,
    ammAbi,
    deployment.token0,
    wallets.map((wallet) => ({ wallet, amountIn: parseUnits("100", 18) })),
  );
  console.log(`  block ${naive.blockNumber} - AMM-scoped:`, naive.ammReport);
  console.log(`  block ${naive.blockNumber} - full (incl. token contracts):`, naive.fullReport);

  console.log(`Firing ${BAND_COUNT} concurrent ShardedAMM swaps (one per band)...`);
  const sharded = await fireConcurrentSwaps(
    provider,
    rpcClient,
    deployment.shardedAmm,
    ammAbi,
    deployment.token0,
    wallets.slice(0, BAND_COUNT).map((wallet, band) => ({
      wallet,
      amountIn: parseUnits("100", 18) + BAND_WIDTH * BigInt(band),
    })),
  );
  console.log(`  block ${sharded.blockNumber} - AMM-scoped:`, sharded.ammReport);
  console.log(`  block ${sharded.blockNumber} - full (incl. token contracts):`, sharded.fullReport);

  if (naive.ammReport.conflictingSlots === 0) {
    throw new Error("REGRESSION: expected NaiveAMM's concurrent swaps to conflict on reserve0/reserve1");
  }
  if (sharded.ammReport.conflictingSlots !== 0) {
    throw new Error("REGRESSION: expected ShardedAMM's one-swap-per-band to show zero conflicts on its own reserve slots");
  }

  console.log("\nOK - NaiveAMM conflicts on its own storage, ShardedAMM (one swap per band) does not.");
  console.log(
    "Note: the *full* report still shows conflicts on the token contracts' balanceOf(AMM) " +
      "slot for both - that's inherent to ERC20 accounting, not something AMM-side sharding fixes.",
  );
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
