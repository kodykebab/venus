import assert from "node:assert/strict";
import { test } from "node:test";

import { countConflicts } from "./conflict_counter.js";
import { extractWriteSet } from "./trace_diff.js";
import type { TxWriteSet } from "./trace_diff.js";

test("no writes -> no conflicts", () => {
  const report = countConflicts([]);
  assert.equal(report.conflictingSlots, 0);
  assert.equal(report.totalTransactions, 0);
});

test("disjoint slots across txs -> zero conflicts (ShardedAMM-like)", () => {
  const writeSets: TxWriteSet[] = [
    { txIndex: 0, slots: new Set(["0xamm:0x1"]) },
    { txIndex: 1, slots: new Set(["0xamm:0x2"]) },
    { txIndex: 2, slots: new Set(["0xamm:0x3"]) },
  ];
  const report = countConflicts(writeSets);
  assert.equal(report.conflictingSlots, 0);
  assert.equal(report.conflictingTransactionPairs, 0);
  assert.equal(report.totalTransactions, 3);
});

test("shared slot across every tx -> near-total conflict (NaiveAMM-like)", () => {
  const writeSets: TxWriteSet[] = [
    { txIndex: 0, slots: new Set(["0xamm:0xreserve0", "0xamm:0xreserve1"]) },
    { txIndex: 1, slots: new Set(["0xamm:0xreserve0", "0xamm:0xreserve1"]) },
    { txIndex: 2, slots: new Set(["0xamm:0xreserve0", "0xamm:0xreserve1"]) },
  ];
  const report = countConflicts(writeSets);
  assert.equal(report.conflictingSlots, 2);
  // C(3,2) = 3 pairs, for each of the 2 conflicting slots.
  assert.equal(report.conflictingTransactionPairs, 6);
  assert.equal(report.transactionsInvolvedInConflict, 3);
});

test("extractWriteSet pulls slots from the prestateTracer diffMode `post` side only", () => {
  const diffResult = {
    pre: { "0xAMM": { storage: { "0x01": "0x00" } } },
    post: { "0xAMM": { storage: { "0x01": "0x05", "0x02": "0x09" } } },
  };
  const ws = extractWriteSet(0, diffResult, "0xhash");
  assert.deepEqual(
    [...ws.slots].sort(),
    ["0xamm:0x01", "0xamm:0x02"],
  );
});
