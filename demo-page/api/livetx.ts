import type { VercelRequest, VercelResponse } from "@vercel/node";
import { Contract, JsonRpcProvider, Wallet, parseUnits } from "ethers";

/** Minimal ABI fragment - only what this endpoint needs. Not sourced from Foundry's
 * build output because that directory isn't guaranteed to exist in the Vercel build
 * environment (it's gitignored, produced locally by `forge build`). */
const MIN_ABI = [
  "function swap(address tokenIn, uint256 amountIn, uint256 minAmountOut) external returns (uint256)",
  "function mint(address to, uint256 amount) external",
  "function approve(address spender, uint256 amount) external returns (bool)",
  "function balanceOf(address account) external view returns (uint256)",
  "function allowance(address owner, address spender) external view returns (uint256)",
];

function monadscanTxUrl(chainId: number, txHash: string): string {
  const base = chainId === 143 ? "https://monadscan.com" : "https://testnet.monadscan.com";
  return `${base}/tx/${txHash}`;
}

/**
 * Live-transaction demo trigger (build spec requirement 3): sends one genuinely new
 * swap() from a dedicated, pre-funded demo wallet and returns once it confirms. The
 * wallet's private key lives only in Vercel's encrypted env vars - never committed.
 */
export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "POST") {
    res.status(405).json({ error: "POST only" });
    return;
  }

  const { RPC_URL, CHAIN_ID, LIVETX_PRIVATE_KEY, NAIVE_AMM_ADDRESS, SHARDED_AMM_ADDRESS, TOKEN0_ADDRESS } = process.env;
  const required = { RPC_URL, LIVETX_PRIVATE_KEY, NAIVE_AMM_ADDRESS, SHARDED_AMM_ADDRESS, TOKEN0_ADDRESS };
  const missing = Object.entries(required)
    .filter(([, value]) => !value)
    .map(([name]) => name);
  if (missing.length > 0) {
    // Names only, never values - safe to expose for debugging a deploy misconfiguration.
    res.status(500).json({ error: `Server misconfigured: missing env var(s): ${missing.join(", ")}` });
    return;
  }

  try {
    const chainId = Number(CHAIN_ID ?? 10143);
    const body = (typeof req.body === "string" ? JSON.parse(req.body) : req.body) ?? {};
    const ammAddress = body.contract === "sharded" ? required.SHARDED_AMM_ADDRESS! : required.NAIVE_AMM_ADDRESS!;
    const amount = parseUnits(String(body.amount ?? "10"), 18);

    const provider = new JsonRpcProvider(required.RPC_URL);
    const wallet = new Wallet(required.LIVETX_PRIVATE_KEY!, provider);
    const amm = new Contract(ammAddress, MIN_ABI, wallet);
    const token0 = new Contract(required.TOKEN0_ADDRESS!, MIN_ABI, wallet);

    let nonce = await provider.getTransactionCount(wallet.address, "latest");

    const balance: bigint = await token0.balanceOf(wallet.address);
    if (balance < amount) {
      await (await token0.mint(wallet.address, amount, { nonce: nonce++ })).wait();
    }

    const allowance: bigint = await token0.allowance(wallet.address, ammAddress);
    if (allowance < amount) {
      await (await token0.approve(ammAddress, amount, { nonce: nonce++ })).wait();
    }

    const tx = await amm.swap(required.TOKEN0_ADDRESS!, amount, 0, { nonce: nonce++, gasLimit: 500_000n });
    const receipt = await tx.wait();

    res.status(200).json({
      txHash: tx.hash,
      monadscanUrl: monadscanTxUrl(chainId, tx.hash),
      blockNumber: receipt.blockNumber,
      status: receipt.status,
    });
  } catch (err) {
    // Never echo the raw error: ethers' network-error objects can embed the
    // request URL - which for a provider like QuickNode carries an auth
    // token in the path - and this endpoint is unauthenticated and public.
    // Full detail goes to the server's own logs (Vercel captures console.error
    // privately); the caller gets a message with no credential in it.
    console.error("livetx failed:", err);
    const message = err instanceof Error ? err.message : String(err);
    const safe = /quiknode|alchemy|infura|ankr|[?&]key=|api[_-]?key/i.test(message)
      ? "The transaction could not be completed. Try again in a moment."
      : message;
    res.status(500).json({ error: safe });
  }
}
