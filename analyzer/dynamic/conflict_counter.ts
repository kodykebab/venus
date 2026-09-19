import type { SlotKey, TxWriteSet } from "./trace_diff.js";

export interface ConflictReport {
  totalTransactions: number;
  /** number of (address, slot) pairs written by more than one transaction in the window. */
  conflictingSlots: number;
  /** sum over conflicting slots of C(writers, 2) - how many tx pairs actually collide. */
  conflictingTransactionPairs: number;
  /** how many distinct transactions wrote at least one contended slot. */
  transactionsInvolvedInConflict: number;
  slotWriterCounts: Record<SlotKey, number>;
}

/**
 * Conflict count = number of (contractAddress, storageSlotKey) pairs written by more
 * than one transaction within the same block window, computed by diffing write-sets
 * across all transactions in the block - never inferred from latency/throughput.
 */
export function countConflicts(writeSets: TxWriteSet[]): ConflictReport {
  const slotWriters = new Map<SlotKey, Set<number>>();

  for (const ws of writeSets) {
    for (const slot of ws.slots) {
      let writers = slotWriters.get(slot);
      if (!writers) {
        writers = new Set();
        slotWriters.set(slot, writers);
      }
      writers.add(ws.txIndex);
    }
  }

  let conflictingSlots = 0;
  let conflictingTransactionPairs = 0;
  const txInvolved = new Set<number>();
  const slotWriterCounts: Record<SlotKey, number> = {};

  for (const [slot, writers] of slotWriters) {
    slotWriterCounts[slot] = writers.size;
    if (writers.size > 1) {
      conflictingSlots += 1;
      conflictingTransactionPairs += (writers.size * (writers.size - 1)) / 2;
      for (const txIndex of writers) txInvolved.add(txIndex);
    }
  }

  return {
    totalTransactions: writeSets.length,
    conflictingSlots,
    conflictingTransactionPairs,
    transactionsInvolvedInConflict: txInvolved.size,
    slotWriterCounts,
  };
}
