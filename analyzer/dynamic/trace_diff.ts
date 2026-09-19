/** (contractAddress, storageSlotKey) pair, encoded as "address:slot" (both lowercased). */
export type SlotKey = string;

export interface TxWriteSet {
  txIndex: number;
  txHash?: string;
  slots: Set<SlotKey>;
}

interface PrestateAccountDiff {
  storage?: Record<string, string>;
}

interface PrestateDiffResult {
  pre?: Record<string, PrestateAccountDiff>;
  post?: Record<string, PrestateAccountDiff>;
}

function slotKey(address: string, slot: string): SlotKey {
  return `${address.toLowerCase()}:${slot.toLowerCase()}`;
}

/** Extracts the (address, slot) write-set for one transaction from a prestateTracer
 * diffMode result - the `post` side lists exactly the slots that transaction wrote. */
export function extractWriteSet(txIndex: number, diffResult: PrestateDiffResult, txHash?: string): TxWriteSet {
  const slots = new Set<SlotKey>();
  for (const [address, accountDiff] of Object.entries(diffResult.post ?? {})) {
    for (const slot of Object.keys(accountDiff.storage ?? {})) {
      slots.add(slotKey(address, slot));
    }
  }
  return { txIndex, txHash, slots };
}

/** debug_traceBlockByNumber returns one entry per transaction, each shaped like
 * `{ txHash, result: <prestateTracer diffMode result> }`. */
export function extractBlockWriteSets(blockTraceResult: Array<{ txHash?: string; result: PrestateDiffResult }>): TxWriteSet[] {
  return blockTraceResult.map((entry, i) => extractWriteSet(i, entry.result, entry.txHash));
}

/**
 * Restricts write-sets to slots on one contract address. A swap always also writes the
 * ERC20 token contracts' `balanceOf(AMM)` slot (every trade moves the AMM's own token
 * balance) - that's a real, unavoidable conflict at the token-contract level regardless
 * of how the AMM shards its own reserves, but it isn't something the AMM's own storage
 * layout can fix. Scoping to the AMM's address keeps the dynamic measurement aligned
 * with what the static analyzer evaluates (the target contract's own state variables).
 */
export function filterToAddress(writeSets: TxWriteSet[], address: string): TxWriteSet[] {
  const target = address.toLowerCase();
  return writeSets.map((ws) => ({
    ...ws,
    slots: new Set([...ws.slots].filter((slot) => slot.startsWith(`${target}:`))),
  }));
}
