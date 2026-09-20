# Testing ParaCheck

Minimal guide to running and verifying each piece. See [README.md](README.md) for setup
(Foundry, Python venv, `npm install`) and contract addresses.

## 1. Contracts

```bash
cd contracts
forge test -vv
```
Expect `18 passed, 0 failed`. Covers normal swaps, boundary amounts, band-boundary edges
(ShardedAMM), zero-amount rejection, and reentrancy against a malicious-callback token.

## 2. Static analyzer

```bash
cd analyzer/static
export PATH="$HOME/.foundry/bin:../.venv/bin:$PATH"
../.venv/bin/python3 -m pytest test_classifier.py -v
```
Expect `6 passed` — three hand-written fixtures (global counter → hot, per-user mapping →
safe, inline assembly → `unanalyzable` not a crash) plus regression checks against the
real `NaiveAMM`/`ShardedAMM`. Note the venv lives at `analyzer/.venv` (one level up from
this directory), not inside `static/` itself - that's where `cli.ts`'s `paracheck analyze`
expects to find it too. `export` (not an inline `VAR=val` prefix) matters here - later
lines in the same block need it too, not just the first.

Run it directly against the example fixture contracts in `analyzer/static/fixtures/`
(these are the hand-written known-correct cases the pytest suite above checks against):

```bash
cd analyzer/static
export PATH="$HOME/.foundry/bin:../.venv/bin:$PATH"

../.venv/bin/python3 report.py \
  fixtures/GlobalCounter.sol GlobalCounter fixtures/GlobalCounter.sol
# -> parallelismScore: 0, "count" flagged hot (touched by increment + incrementBy)

../.venv/bin/python3 report.py \
  fixtures/PerUserMapping.sol PerUserMapping fixtures/PerUserMapping.sol
# -> parallelismScore: 100, no flags (mapping indexed by msg.sender)

../.venv/bin/python3 report.py \
  fixtures/InlineAssemblyContract.sol InlineAssemblyContract fixtures/InlineAssemblyContract.sol
# -> unanalyzable: true, "manual review recommended" - never a crash
```

Or against the real demo contracts (a Foundry project path + contract name + source file):
```bash
cd analyzer/static
export PATH="$HOME/.foundry/bin:../.venv/bin:$PATH"

../.venv/bin/python3 report.py ../../contracts NaiveAMM ../../contracts/src/NaiveAMM.sol
# -> parallelismScore: 0, reserve0/reserve1 both hot (touched by addLiquidity + swap)

../.venv/bin/python3 report.py ../../contracts ShardedAMM ../../contracts/src/ShardedAMM.sol
# -> parallelismScore: 50, safeFunctions: ["swap"], only addLiquidity flagged hot
```

## 2a. Claude synthesis (real API, optional)

This is the only check that needs a real Anthropic API key. Put
`ANTHROPIC_API_KEY=sk-ant-...` in the repository's `.env`, then run:

```bash
./paracheck review analyzer/static/fixtures/VulnerableSample.sol \
  --out /tmp/paracheck-claude-review.md
cat /tmp/paracheck-claude-review.md
```

This exercises the live `messages.parse` call and writes the review outside the
repository. The key is optional: without it, the same command renders the raw
findings deterministically. API billing is separate from a Claude.ai
subscription.

## 3. Dynamic analyzer (local, no testnet needed)

```bash
anvil --network monad &
cd contracts
forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 \
  --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  --broadcast

cd ../analyzer
npx tsx --test dynamic/conflict_counter.test.ts   # unit tests, no network
RPC_URL=http://127.0.0.1:8545 CHAIN_ID=31337 npx tsx dynamic/local_validate.ts
```
`local_validate.ts` fires concurrent swaps at both contracts on local anvil and asserts:
NaiveAMM's swaps conflict on its reserve slots, ShardedAMM's (one per band) don't. Exits
non-zero on a regression.

## 4. Dynamic analyzer (real Monad Testnet)

Needs a `debug_*`-capable RPC endpoint (dedicated QuickNode - not the shared public tier
or Ankr's public endpoint, both of which block/rate-limit debug methods).

```bash
cd analyzer
RPC_URL=<testnet rpc> DYNAMIC_RPC_URL=<testnet rpc with debug_*> CHAIN_ID=10143 \
LOADTEST_PRIVATE_KEYS=<key1,key2,key3,key4,key5> \
  npx tsx cli.ts loadtest --chain-id 10143 --traders 5 --bands 3
```
Writes `demo-page/reports/dynamic-comparison.json`. Check `ammReport.conflictingSlots`:
non-zero for NaiveAMM, zero for ShardedAMM.

## 5. Live-transaction trigger

```bash
cd analyzer
RPC_URL=<testnet rpc> CHAIN_ID=10143 LIVETX_PRIVATE_KEY=<funded demo wallet key> \
  npx tsx cli.ts livetx --contract naive --amount 10
```
Should print a tx hash, a Monadscan link, and `status=1` within a few seconds. Run it a
few times against both `--contract naive` and `--contract sharded` - it should be
reliable every time, not flaky.

## 6. Demo page

Local:
```bash
cd demo-page
python3 -m http.server 8080
# open http://localhost:8080 - static cards + dynamic bars should render from reports/*.json
```
The live-tx button needs `api/livetx.ts` running, which only works deployed on Vercel
(it's a serverless function, not something a static file server can execute) - see
README for the Vercel env vars.

Production checklist (from a device that isn't your dev machine):
- [ ] Both static report cards render, each showing a "Safe" section for functions with
      no hot-slot touches (not just an absence from the hot list)
- [ ] Dynamic conflict-count bars render
- [ ] Both contract addresses link out to Monadscan
- [ ] "Fire live swap" button sends a real transaction and shows a working Monadscan link

## 7. Clean-clone check

```bash
git clone https://github.com/kodykebab/venus /tmp/paracheck-clean
cd /tmp/paracheck-clean
# follow README.md's setup + steps 1-3 above with no other local state
```
Confirms the repo works from nothing but its own README - no local files or memory of
this machine's setup required.
