# ParaCheck

A parallelism-conflict analysis tool for Monad smart contracts, proven on two
demonstration AMM contracts with real, measured on-chain data.

Monad's optimistic parallel execution runs transactions in parallel assuming no
conflicts, then merges them serially - any transaction whose read state was altered by
an earlier one in the same block gets **re-executed**. A contract with naive storage
layout (one global counter, one global reserve pair, one shared mapping key) forces every
transaction through that conflict/re-execution path, silently turning "parallel
execution" into "sequential execution with overhead." ParaCheck tells you which
functions will do that, two ways:

1. **Static analyzer** - reads a contract's storage access patterns (via
   [Slither](https://github.com/crytic/slither)) and flags which functions will conflict
   with each other under concurrent execution.
2. **Dynamic analyzer** - fires real transactions and measures actual storage-slot
   conflicts using Monad's `debug_traceBlockByNumber` / `prestateTracer` trace API - real
   measured data, not an inferred/proxy metric.

It's demonstrated on `NaiveAMM` (a naive single-reserve-slot constant-product AMM that
conflicts heavily under concurrent load) and `ShardedAMM` (an identical-interface AMM
whose reserves are split across price bands, which conflicts far less).

## Live demo

- Demo page: **_pending - not yet deployed (Vercel import pending)_**
- `NaiveAMM`: [`0x65a0C262a20a34568242ABD95894C79E28CC5Fb8`](https://testnet.monadscan.com/address/0x65a0C262a20a34568242ABD95894C79E28CC5Fb8) (verified)
- `ShardedAMM`: [`0x3e3b4e31931f341F10E0f102ff885357Ac5D3834`](https://testnet.monadscan.com/address/0x3e3b4e31931f341F10E0f102ff885357Ac5D3834) (verified, 3 bands)
- Demo tokens: [`token0`](https://testnet.monadscan.com/address/0x6cAC62D51748d7387C0fE6ce27BEa1B609E60362) / [`token1`](https://testnet.monadscan.com/address/0x2d7815f4882a27E9e4Eb39262A266fC11589C79e) (verified)

Both contracts are deployed and source-verified on Monad Testnet (chain `10143`). Real
measured results from `paracheck loadtest` against these exact deployed contracts: 5
concurrent `NaiveAMM` swaps landed in the same block and produced 2 conflicting storage
slots (all 5 transactions mutually conflicting); 3 concurrent `ShardedAMM` swaps, one per
band, landed in the same block and produced **zero** conflicts. See
`demo-page/reports/dynamic-comparison.json` for the full trace-derived data.

## Repo layout

```
contracts/       Foundry project: NaiveAMM, ShardedAMM, DemoToken, tests, deploy script
analyzer/
  static/        Python/Slither static analyzer (run_slither.py, classify.py, report.py)
  dynamic/       TypeScript dynamic analyzer (rpc_client, trace_diff, conflict_counter)
  cli.ts         `paracheck analyze|loadtest|livetx|deployment-info`
demo-page/       Static demo page + Vercel serverless live-tx endpoint
```

## How ShardedAMM works

Same external interface and behavior as `NaiveAMM` (`swap`, `addLiquidity`,
`getReserves`), but reserves are split across a constructor-configurable number of price
bands (default 3), each with its own independent reserve pair. Which band a swap lands in
is a deterministic function of swap size (`bandOf(amountIn) = (amountIn / bandWidth) %
bandCount`), so swaps of different sizes touch different storage slots and don't conflict
with each other.

## CLI

A single `paracheck` wrapper at the repo root dispatches to everything else:

```bash
./paracheck contracts/samples/StakingPoolSample.sol   # analyze one Solidity file
./paracheck analyze                                    # regenerate demo-page static reports
./paracheck loadtest --chain-id 10143 --traders 5 --bands 3
./paracheck livetx --contract naive --amount 5
./paracheck deployment-info --chain-id 10143
./paracheck config                                      # show resolved config + where it came from
./paracheck --help
```

A `.sol` path is analyzed directly (single, importless file - no `import` resolution);
anything else forwards to `analyzer/cli.ts`. Non-secret defaults (Python venv path,
Foundry bin directory, chain ID) come from [`paracheck.json`](paracheck.json) at the repo
root, falling back to `config.json` if that file doesn't exist - `paracheck config` shows
exactly what got resolved. Secrets never go in either file: `loadtest`/`livetx` still read
`RPC_URL`, `DYNAMIC_RPC_URL`, `LOADTEST_PRIVATE_KEYS`, `LIVETX_PRIVATE_KEY` from `.env` /
your shell environment, same as always. Global flags (`--config`, `--venv`,
`--foundry-bin`) override the config file and must come before the command.

## GitHub Action

[`.github/actions/analyze`](.github/actions/analyze) wraps the same static classifier as a
reusable composite Action - point it at one self-contained Solidity file (no `import`s,
same constraint as `paracheck <file>.sol`) and it posts a summary comment on the PR, with
an optional score threshold to fail the job outright. No server, no GitHub App, no OAuth -
just the repo's own built-in `GITHUB_TOKEN`.

```yaml
# .github/workflows/paracheck.yml
on:
  pull_request:
    paths: ["src/MyContract.sol"]

permissions:
  contents: read
  pull-requests: write   # required for the PR comment

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: kodykebab/venus/.github/actions/analyze@main
        with:
          contract-path: src/MyContract.sol
          fail-below-score: "50"   # optional - omit to report-only, never fail the job
```

| Input | Required | Default | Meaning |
|---|---|---|---|
| `contract-path` | yes | - | Path to a single, self-contained `.sol` file |
| `fail-below-score` | no | `""` (never fails) | Fail the job if the lowest parallelism score is below this |
| `comment-on-pr` | no | `"true"` | Post the summary as a PR comment |
| `github-token` | no | `${{ github.token }}` | Only needed if the default token can't comment (e.g. some fork PR setups) |

Output: `report-json` (the raw JSON, same shape as everywhere else on this project).

[`.github/workflows/paracheck-analyze.yml`](.github/workflows/paracheck-analyze.yml) in
this repo is both the reference example and a live self-test - it runs the action against
[`contracts/samples/StakingPoolSample.sol`](contracts/samples/StakingPoolSample.sol) on
every PR that touches it.

**Known limitation**, same as the CLI and the web upload page: single self-contained file
only, no `import` resolution - a contract that imports other files comes back
`unanalyzable` with a clear reason, not a crash or a wrong answer.

## Running it yourself

### Prerequisites
- [Foundry](https://book.getfoundry.sh/) ≥ v1.8.0 (has native Monad support via
  `network = "monad"` in `foundry.toml` - no separate Monad-patched fork needed):
  `curl -L https://foundry.paradigm.xyz | bash && foundryup`
- Node.js 18+
- Python 3.8+
- A Monad Testnet RPC endpoint with `debug_*` support for the dynamic analyzer (a
  dedicated QuickNode endpoint - the shared public QuickNode endpoint and Ankr's public
  endpoint both either rate-limit or block `debug_*` methods)

### Setup
```bash
cp .env.example .env   # fill in RPC_URL / DYNAMIC_RPC_URL / keys as needed

# contracts
cd contracts && forge install && forge build && forge test

# static analyzer - venv lives at analyzer/.venv (cli.ts's `paracheck analyze` expects it there)
cd ../analyzer
python3 -m venv .venv && .venv/bin/pip install -r static/requirements.txt
.venv/bin/solc-select install 0.8.24 && .venv/bin/solc-select use 0.8.24
cd static
PATH="$HOME/.foundry/bin:../.venv/bin:$PATH" ../.venv/bin/python3 -m pytest test_classifier.py -v

# dynamic analyzer / CLI
cd ../
npm install
```

### Local end-to-end check (no testnet needed)
```bash
anvil --network monad &
cd contracts
forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 \
  --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  --broadcast

cd ../analyzer
RPC_URL=http://127.0.0.1:8545 CHAIN_ID=31337 npx tsx dynamic/local_validate.ts
```
This deploys both contracts to local anvil, fires concurrent swaps at each, traces the
resulting block, and asserts NaiveAMM's swaps conflict on its reserve slots while
ShardedAMM's (spread one per band) don't.

### Static + dynamic reports for the demo page
```bash
cd analyzer
npx tsx cli.ts analyze                 # writes demo-page/reports/static-*.json
npx tsx cli.ts deployment-info --chain-id 10143
npx tsx cli.ts loadtest --chain-id 10143 --traders 5 --bands 3
```

### Firing a live transaction yourself
```bash
cd analyzer
RPC_URL=<testnet rpc> CHAIN_ID=10143 LIVETX_PRIVATE_KEY=<funded demo wallet key> \
  npx tsx cli.ts livetx --contract naive --amount 10
```
Prints the transaction hash and a Monadscan link once it confirms. The same code path
backs the "fire a live swap" button on the demo page, via
`demo-page/api/livetx.ts` (a Vercel serverless function holding the demo wallet's key as
an encrypted env var - never committed).

## Known limitations

1. The static pass detects known hot-slot patterns via Slither's read/write extraction;
   contracts with heavy inline assembly are explicitly flagged as "not fully analyzable"
   rather than silently passed as safe (`analyzer/static/run_slither.py`).
2. Dynamic conflict counts are real, measured data from `prestateTracer` diffs - not
   inferred from latency - but reflect the specific load pattern tested, not a general
   prediction for arbitrary future usage patterns.
3. `ShardedAMM`'s price-banding is a simplified, parameterized illustrative fix, not
   production-grade concentrated-liquidity math.
4. Band-sharding removes conflicts on the AMM's *own* reserve accounting, but every swap
   still writes the paired ERC20 tokens' `balanceOf(AMM)` slot regardless of band - that's
   inherent to ERC20 accounting (a single contract's aggregate token balance is always one
   slot), not something either AMM's storage layout can fix. The dynamic analyzer reports
   this scoped to the AMM's own storage (matching what the static analyzer evaluates) and
   separately as a full cross-contract trace, so both numbers are visible.

## License

MIT - see [LICENSE](LICENSE).
