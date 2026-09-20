"""Which chain a contract targets changes which findings are real.

Parallelism-conflict analysis only means anything on a chain that executes
transactions optimistically in parallel. Reporting contended storage slots on
Ethereum L1 - where execution is sequential by design - would be noise dressed
up as a finding, and is exactly the kind of thing that trains people to ignore
a tool.

So the parallelism pass is gated on a capability, not assumed. Everything
Slither checks (reentrancy, access control, unchecked sends) is execution-model
independent and always runs.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chain:
    key: str
    name: str
    chain_id: int | None
    # Optimistic parallel execution: transactions run concurrently and anything
    # that touches state an earlier transaction wrote gets re-executed.
    parallel_execution: bool
    # Fees charged on the declared gas limit rather than gas actually used, so
    # over-declaring costs real money.
    charges_declared_gas: bool = False
    notes: str = ""

    @property
    def runs_parallelism_analysis(self) -> bool:
        return self.parallel_execution


CHAINS: dict[str, Chain] = {
    "monad": Chain(
        "monad", "Monad", 143, parallel_execution=True, charges_declared_gas=True,
        notes="Optimistic parallel execution; fees charged on the declared gas limit.",
    ),
    "monad-testnet": Chain(
        "monad-testnet", "Monad Testnet", 10143, parallel_execution=True, charges_declared_gas=True,
        notes="Optimistic parallel execution; fees charged on the declared gas limit.",
    ),
    "sei": Chain(
        "sei", "Sei", 1329, parallel_execution=True,
        notes="Parallel EVM execution.",
    ),
    "megaeth": Chain(
        "megaeth", "MegaETH", None, parallel_execution=True,
        notes="Parallel EVM execution.",
    ),
    "ethereum": Chain("ethereum", "Ethereum", 1, parallel_execution=False),
    "arbitrum": Chain("arbitrum", "Arbitrum One", 42161, parallel_execution=False),
    "optimism": Chain("optimism", "OP Mainnet", 10, parallel_execution=False),
    "base": Chain("base", "Base", 8453, parallel_execution=False),
    "polygon": Chain("polygon", "Polygon PoS", 137, parallel_execution=False),
    "bsc": Chain("bsc", "BNB Smart Chain", 56, parallel_execution=False),
    "avalanche": Chain("avalanche", "Avalanche C-Chain", 43114, parallel_execution=False),
}

DEFAULT_CHAIN = "monad"

# Any EVM chain we don't know by name: run the universal checks, and don't
# claim anything about its execution model.
UNKNOWN_EVM = Chain("evm", "EVM-compatible chain", None, parallel_execution=False,
                    notes="Unrecognized chain - parallelism analysis skipped.")


def resolve_chain(identifier: str | int | None) -> Chain:
    """Accepts a key ('monad'), a chain id (10143), or None for the default."""
    if identifier is None:
        return CHAINS[DEFAULT_CHAIN]

    if isinstance(identifier, int) or str(identifier).isdigit():
        wanted = int(identifier)
        for chain in CHAINS.values():
            if chain.chain_id == wanted:
                return chain
        return UNKNOWN_EVM

    key = str(identifier).strip().lower()
    return CHAINS.get(key, UNKNOWN_EVM)


def parallel_chains() -> list[Chain]:
    return [c for c in CHAINS.values() if c.parallel_execution]
