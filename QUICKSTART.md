# ParaCheck Quickstart

Copy-paste commands only. Fill in `<...>` from your `.env` / `keystores/testnet-wallets.txt`
(never commit those values). See [TESTING.md](TESTING.md) for the full walkthrough.

```bash
cd ~/projects/venus
export PATH="$HOME/.foundry/bin:$PATH"
```

### Run everything local (no secrets needed)

```bash
(cd contracts && forge test -vv)

(cd analyzer/static && PATH="$HOME/.foundry/bin:.venv/bin:$PATH" .venv/bin/python3 -m pytest test_classifier.py -v)
```

### Local dynamic check on anvil

```bash
anvil --network monad &

cd contracts
forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 \
  --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  --broadcast

cd ../analyzer
RPC_URL=http://127.0.0.1:8545 CHAIN_ID=31337 npx tsx dynamic/local_validate.ts
```

### Real Monad Testnet - regenerate demo-page reports

```bash
cd ~/projects/venus/analyzer
npx tsx cli.ts analyze
npx tsx cli.ts deployment-info --chain-id 10143

RPC_URL=<testnet rpc> DYNAMIC_RPC_URL=<testnet rpc with debug_*> CHAIN_ID=10143 \
LOADTEST_PRIVATE_KEYS=<key1,key2,key3,key4,key5> \
  npx tsx cli.ts loadtest --chain-id 10143 --traders 5 --bands 3
```

### Fire one live transaction on Monad Testnet

```bash
cd ~/projects/venus/analyzer
RPC_URL=<testnet rpc> CHAIN_ID=10143 LIVETX_PRIVATE_KEY=<funded demo wallet key> \
  npx tsx cli.ts livetx --contract naive --amount 5
```

Prints a tx hash + Monadscan link, confirms in a few seconds.
