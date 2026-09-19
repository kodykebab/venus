# ParaCheck — Build Handoff

You are building **ParaCheck**: a parallelism-conflict analysis tool for Monad smart contracts,
plus two demonstration contracts that prove it works with real, measured on-chain data. This
document is self-contained — build directly from it.

## Project summary

Monad's core value proposition is optimistic parallel execution: transactions run in parallel
assuming no conflicts, then merge serially, with any transaction whose read state was altered by
an earlier one in the same block getting **re-executed**. A contract written with naive storage
layout (one global counter, one global reserve pair, one shared mapping key) forces every
transaction through the conflict/re-execution path — silently turning "parallel execution" into
"sequential execution with overhead." Nobody currently tells Solidity developers this.

ParaCheck is a two-part tool:
1. A **static analyzer** that reads a contract's storage access patterns and flags which
   functions will conflict with each other under concurrent execution.
2. A **dynamic analyzer** that fires real transactions and measures actual storage-slot conflicts
   using Monad's transaction trace API — not an inferred/proxy metric, real measured data.

It proves itself using two demonstration contracts: `NaiveAMM` (a naive single-reserve-slot AMM
that will conflict heavily) and `ShardedAMM` (an identical-interface AMM with reserves split into
price bands, which conflicts far less).

## Hard requirements — build is not done until all four hold

1. **Public GitHub repo** with working code and a README containing both contract addresses, the
   public demo page URL, and clear run-it-yourself instructions.
2. **Both contracts deployed and verified on Monad Testnet** (chain ID `10143`).
3. **A real, working "fire a live transaction" path** — a button on the demo page (or CLI command)
   that sends a genuinely new transaction to the deployed contracts and shows it confirm in real
   time, linking to the transaction on Monadscan. This must not be a replay or a reference to a
   past transaction — it has to work freshly, on demand, repeatedly.
4. **A public demo page** (single static HTML/JS page is sufficient) that on its own, without
   anyone running anything locally, shows: the static analyzer's report for both contracts, the
   dynamic analyzer's measured conflict-count comparison for both contracts, the live-transaction
   trigger from (3), and both contract addresses linked to Monadscan.

No mainnet deployment, no custom domain, no social/marketing deliverables — those are explicitly
out of scope for this build.

---

## Architecture decisions (build against these, don't relitigate them)

### Static analyzer — use Slither, do not hand-roll a Solidity parser
Use Slither's Python API for read/write extraction:
```python
function.state_variables_read     # list[StateVariable]
function.state_variables_written  # list[StateVariable]
```
This correctly handles inheritance and internal calls without a fragile custom parser.

**Classification rules to implement:**
- A state variable that is a **fixed global slot** (plain value type or a struct field not
  indexed by a mapping/array) touched by more than one externally-callable function → flag **hot**.
- A **mapping/array indexed by `msg.sender` or a function parameter** → classify **safe** (each
  key resolves to an independently computed slot via `keccak256(key, baseSlot)`, so different
  callers don't collide with each other).
- A **mapping/array indexed by a shared/fixed key** (not caller-specific) → flag **hot**, same
  treatment as a global slot.

**Mandatory failure handling:** Slither can fail SSA conversion on contracts with heavy inline
assembly (`sstore`/`sload` blocks). Wrap analysis in try/catch. On failure, or when inline
assembly is detected in source, output: `"This contract contains constructs that couldn't be
statically analyzed — manual review recommended"` — never crash silently, never silently skip.

**Output:** a JSON report shaped like:
```json
{
  "contract": "NaiveAMM",
  "parallelismScore": 12,
  "flags": [
    { "slot": "reserve0", "touchedBy": ["swap", "addLiquidity"], "severity": "hot",
      "suggestedFix": "shard reserves across price bands" }
  ],
  "unanalyzable": false
}
```

### Dynamic analyzer — real trace-based conflict counting, not a proxy metric
Use `debug_traceTransaction` / `debug_traceBlockByNumber` with `prestateTracer` and
`diffMode: true`:
```json
{ "tracer": "prestateTracer", "tracerConfig": { "diffMode": true } }
```
This returns `pre`/`post` account state including exact storage slot keys written per transaction.

**Two mandatory, easy-to-silently-break requirements:**
- **Always pass the tracer config object explicitly, on every call, even trivial ones.** Monad
  returns `-32602 Invalid params` if the trace-options parameter is omitted — unlike most EVM
  clients where it's optional. Do not write a call path that ever omits it.
- **Use an RPC endpoint that supports `debug_*` methods.** Ankr's public Monad Testnet endpoint
  explicitly disallows debug methods and must not be used. Use a QuickNode endpoint (public
  endpoint supports debug, but get a free **dedicated** QuickNode endpoint rather than the shared
  public one — the shared one has a 25 rps sub-limit on `eth_call`/`eth_estimateGas` and you want
  headroom during live demos) or the Monad Foundation RPC endpoint.

**Conflict count definition:** the number of `(contractAddress, storageSlotKey)` pairs written by
more than one transaction within the same block window. Compute this by diffing write-sets across
all transactions in the block, not by inferring from latency or throughput.

**Efficiency:** prefer one `debug_traceBlockByNumber` call over looping `debug_traceTransaction`
per hash where possible, to conserve RPC rate-limit headroom.

### Demonstration contracts
- `NaiveAMM.sol` — minimal constant-product AMM with a single global `reserve0`/`reserve1` pair.
  Every `swap()` call reads and writes both slots → guaranteed conflict between any two
  concurrent swaps.
- `ShardedAMM.sol` — **identical external function signatures and behavior** to `NaiveAMM` from a
  caller's perspective, but internally splits reserves into a **parameterized number of fixed price
  bands** (constructor argument, default 3), each band with its own independent reserve slot pair.
  Swaps landing in different bands touch different slots and do not conflict. Making band count a
  constructor parameter is required — it lets the demo page show "more bands → lower conflict
  rate" as a comparison rather than one fixed number.
- Both contracts require full test coverage (Foundry) before any deployment or load testing:
  normal swaps, boundary amounts, band-boundary edge cases (`ShardedAMM` only), zero-amount
  rejection, and reentrancy protection verified against a malicious-callback mock token.

### Live-transaction trigger (Requirement 3 above)
- Keep 2–3 dedicated Testnet wallets funded specifically for firing live demo transactions,
  separate from any wallets used in bulk load-testing (fund from `faucet.monad.xyz`, note the
  12-hour cooldown per address — fund these well ahead of any demo, not last-minute).
- Build a minimal endpoint/CLI command that sends one real `swap()` transaction to a deployed
  contract using the dedicated RPC endpoint, and polls for the receipt.
- Monad's finality is ~300–600ms — this should confirm fast enough to show live without dead air,
  but test this path repeatedly against real Testnet before considering it done.
- Link the resulting transaction hash directly to Monadscan so it's independently verifiable.

### Demo page
Single static page is sufficient. Must render:
1. Static report (Parallelism Score + flagged hot slots, plain-English) for both contracts,
   side by side or toggled.
2. Dynamic conflict-count comparison for both contracts (chart or clear table) — if band count is
   implemented as a parameter, show conflict rate across a couple of band-count values here.
3. A visible, working "fire a live transaction" control tied to the live-tx trigger above.
4. Both contract addresses, each linked to Monadscan.
Backend needs are minimal — pre-generated JSON reports committed to the repo, plus whatever
minimal handler is needed to actually send the live transaction.

---

## Project structure

```
paracheck/
├── contracts/
│   ├── src/
│   │   ├── NaiveAMM.sol
│   │   ├── ShardedAMM.sol           # band count as constructor param
│   │   └── interfaces/IAMM.sol
│   ├── test/
│   │   ├── NaiveAMM.t.sol
│   │   └── ShardedAMM.t.sol
│   ├── script/
│   │   └── Deploy.s.sol             # deploys both to Monad Testnet
│   └── foundry.toml                 # network = "monad"
├── analyzer/
│   ├── static/
│   │   ├── run_slither.py           # wraps Slither, extracts read/write sets
│   │   ├── classify.py              # hot-slot vs safe classification
│   │   └── report.py                # emits JSON report
│   ├── dynamic/
│   │   ├── rpc_client.ts            # debug_trace* wrapper, ALWAYS explicit tracerConfig
│   │   ├── trace_diff.ts            # extracts (address, slot) write-sets from prestateTracer
│   │   └── conflict_counter.ts      # cross-tx overlap → conflict count
│   └── cli.ts                       # `paracheck analyze`, `paracheck loadtest`, `paracheck livetx`
├── demo-page/
│   ├── index.html                   # the public demo page
│   ├── reports/                     # pre-generated static + dynamic JSON reports, committed
│   └── live-tx-endpoint/            # minimal handler for the live-tx trigger
├── .env.example                     # RPC URL (dedicated QuickNode/Monad Foundation), chain ID
├── README.md                        # contract addresses, live demo page URL, run-it-yourself steps
└── LICENSE
```

---

## Environment / setup

- Install **Monad Foundry** (a Monad-patched fork of Foundry, not vanilla Foundry) — provides
  `forge`, `cast`, `anvil`, `chisel` with Monad's gas model, opcode pricing, and precompile
  behavior built in, both locally and when forking.
- `anvil --monad` for local development against Monad-accurate execution semantics.
- Node.js 18+ for the TypeScript analyzer/CLI pieces; Python 3.8+ for Slither.
- Chain ID `10143` (Monad Testnet). Faucet: `faucet.monad.xyz`. Explorer: Monadscan
  (`testnet.monadscan.com`).
- **RPC: use a dedicated QuickNode endpoint or the Monad Foundation RPC endpoint. Never Ankr's
  public endpoint — it blocks `debug_*` methods, which the dynamic analyzer depends on entirely.**

---

## Build order

1. Set up environment (Monad Foundry, local anvil, `.env` with dedicated RPC + chain ID 10143).
   Fund 2–3 dedicated live-demo wallets from the faucet immediately (12-hour cooldown applies).
2. Build the static analyzer: wire up Slither, implement classification logic, validate against
   2–3 hand-written fixture contracts with known-correct expected output (a trivial global counter
   contract → should flag hot; a per-user mapping contract → should classify safe) before touching
   the real AMM contracts.
3. Write `NaiveAMM.sol` and `ShardedAMM.sol` (band count parameterized on the latter). Write and
   pass full Foundry test coverage against local Monad-accurate anvil before deploying anywhere.
4. Build the dynamic analyzer: RPC client (explicit tracer config on every call, no exceptions),
   trace diff extraction, conflict counter. Validate locally first — confirm real conflicts show
   up on `NaiveAMM` and are absent (or reduced, band-count-dependent) on `ShardedAMM`, repeatably.
5. Deploy both contracts to Monad Testnet, verify via `forge verify-contract`, confirm on
   Monadscan.
6. Build the live-transaction trigger (CLI + page-integrated version). Test repeatedly against
   real Testnet using the dedicated RPC endpoint until reliable.
7. Build `demo-page/index.html` wiring in the static report, dynamic comparison, live-tx button,
   and contract addresses. Host it publicly. Confirm it works from a device that isn't the dev
   machine.
8. Full end-to-end rehearsal: load demo page → view static report → view dynamic comparison →
   fire a live transaction → confirm on Monadscan. Repeat until reliable, not just once.

---

## Testing / correctness checklist (all required before considering this done)

- [ ] Static classifier fixture tests pass with known-correct expected flags.
- [ ] Slither failure/inline-assembly path tested explicitly — confirms graceful "manual review
      recommended" output, never a crash or silent skip.
- [ ] `NaiveAMM`/`ShardedAMM` pass full Foundry test suites (normal swaps, boundary amounts,
      band-boundary edges, zero-amount rejection, reentrancy guard against a malicious mock token).
- [ ] Every `debug_trace*` call in the codebase passes an explicit `tracerConfig` — grep to verify,
      don't rely on memory.
- [ ] Dynamic conflict counter shows zero false positives on `ShardedAMM` with trades spread
      across bands, and near-total conflict on `NaiveAMM`, repeatably on local anvil.
- [ ] Both contracts verified on Monadscan (published source matches deployed bytecode).
- [ ] Live-tx trigger tested repeatedly against real Testnet via the dedicated RPC endpoint —
      confirms reliable multi-second confirmation, not flaky.
- [ ] Demo page tested from a separate device/browser — reports render, live-tx button actually
      works end to end.
- [ ] Clean-clone test: fresh clone, README-only instructions, confirms everything works without
      the original author intervening.
- [ ] All live-demo wallets funded and balances confirmed well ahead of any demo/deadline.

---

## Known limitations to state plainly in the README (do not hide these)

1. The static pass detects known hot-slot patterns via Slither's read/write extraction; contracts
   with heavy inline assembly or delegatecall-based storage indirection are explicitly flagged as
   "not fully analyzable" rather than silently passed as safe.
2. Dynamic conflict counts are real, measured data from `prestateTracer` diffs — not inferred from
   latency — but reflect the specific load pattern tested, not a general prediction for arbitrary
   future usage patterns.
3. `ShardedAMM`'s price-banding is a simplified, parameterized illustrative fix, not
   production-grade concentrated-liquidity math.
