"""Dynamic review: measure real storage conflicts before the code is deployed.

Static analysis says a slot *looks* contended. This proves it, by actually
running the contract: spin up a local chain (optionally forking real state),
deploy the contract under review, fire concurrent transactions into a single
block, and diff the per-transaction storage writes out of the execution trace.

A pull request's contract isn't deployed anywhere yet, which is why this forks
rather than measuring a live address.

What to simulate cannot be inferred for an arbitrary contract - constructor
arguments, which function carries load, and what realistic concurrency looks
like are all project knowledge. So it's declared (see SimulationSpec), and
skipped entirely when it isn't.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

# anvil's well-known unlocked dev accounts - no client-side signing needed.
ANVIL_ACCOUNTS = [
    "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
    "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
    "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
    "0x976EA74026E726554dB657fA54763abd0C3a0aa9",
    "0x14dC79964da2C08b23698B3D3cc7Ca32193d9955",
]

STARTUP_TIMEOUT_SECONDS = 30
COMMAND_TIMEOUT_SECONDS = 120


@dataclass
class Call:
    """One contract call: a solidity signature plus its arguments."""
    signature: str  # e.g. "stake()" or "swap(address,uint256,uint256)"
    args: list[str] = field(default_factory=list)
    value: str = "0"  # wei, as a decimal string


@dataclass
class SimulationSpec:
    """What to actually run. Declared per project, because none of it is
    inferable from source alone."""
    contract: str
    constructor_args: list[str] = field(default_factory=list)
    constructor_value: str = "0"
    setup: list[Call] = field(default_factory=list)
    concurrent: Call | None = None
    senders: int = 5
    fork_url: str | None = None
    # With automine off, gas estimation runs against a queue of pending
    # transactions and anvil returns "Required data unavailable". An explicit
    # limit skips estimation entirely.
    gas_limit: int = 1_500_000

    @classmethod
    def from_dict(cls, data: dict) -> "SimulationSpec":
        def call(entry: dict) -> Call:
            return Call(
                signature=entry["signature"],
                args=[str(a) for a in entry.get("args", [])],
                value=str(entry.get("value", "0")),
            )

        return cls(
            contract=data["contract"],
            constructor_args=[str(a) for a in data.get("constructorArgs", [])],
            constructor_value=str(data.get("constructorValue", "0")),
            setup=[call(e) for e in data.get("setup", [])],
            concurrent=call(data["concurrent"]) if data.get("concurrent") else None,
            senders=int(data.get("senders", 5)),
            fork_url=data.get("forkUrl"),
            gas_limit=int(data.get("gasLimit", 1_500_000)),
        )


class SimulationError(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run(command: list[str], timeout: int = COMMAND_TIMEOUT_SECONDS) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()[-3:]
        raise SimulationError(f"{command[0]} failed: " + " / ".join(detail))
    return completed.stdout.strip()


class Anvil:
    """A disposable local chain. Forks real state when given an RPC URL, so a
    simulation can run against the storage a contract will actually meet."""

    def __init__(self, fork_url: str | None = None, chain_profile: str = "monad"):
        self.port = _free_port()
        self.fork_url = fork_url
        self.chain_profile = chain_profile
        self.process: subprocess.Popen | None = None

    @property
    def rpc_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "Anvil":
        command = ["anvil", "--port", str(self.port), "--network", self.chain_profile, "--silent"]
        if self.fork_url:
            command += ["--fork-url", self.fork_url]
        self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        deadline = time.time() + STARTUP_TIMEOUT_SECONDS
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise SimulationError("anvil exited during startup")
            try:
                self.rpc("eth_chainId")
                return self
            except Exception:  # noqa: BLE001 - still booting
                time.sleep(0.25)
        raise SimulationError("anvil did not become ready in time")

    def __exit__(self, *exc) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def rpc(self, method: str, *params) -> str:
        return _run(["cast", "rpc", "--rpc-url", self.rpc_url, method, *[str(p) for p in params]])


def compile_contract(source_file: str, contract: str, solc: str | None = None) -> tuple[str, str]:
    """Returns (abi_json, creation_bytecode) for one contract in a source file."""
    output_dir = tempfile.mkdtemp(prefix="paracheck-solc-")
    try:
        _run([solc or "solc", "--combined-json", "abi,bin", "-o", output_dir, "--overwrite", source_file])
        combined = os.path.join(output_dir, "combined.json")
        if not os.path.exists(combined):
            raise SimulationError("solc produced no combined.json")
        with open(combined, encoding="utf-8") as fh:
            data = json.load(fh)
        for key, entry in data.get("contracts", {}).items():
            if key.rsplit(":", 1)[-1] == contract:
                return json.dumps(entry.get("abi", [])), entry.get("bin", "")
        raise SimulationError(f"contract '{contract}' not found in {source_file}")
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def _cast_send(anvil: Anvil, sender: str, extra: list[str], asynchronous: bool = False) -> str:
    command = ["cast", "send", "--rpc-url", anvil.rpc_url, "--unlocked", "--from", sender]
    if asynchronous:
        command.append("--async")
    return _run(command + extra)


def deploy(anvil: Anvil, bytecode: str, spec: SimulationSpec, abi_json: str) -> str:
    """Deploys and returns the contract address."""
    create_args = ["--create", bytecode]
    if spec.constructor_args:
        constructor = next(
            (e for e in json.loads(abi_json) if e.get("type") == "constructor"), None
        )
        types = ",".join(i["type"] for i in (constructor or {}).get("inputs", []))
        create_args += [f"constructor({types})", *spec.constructor_args]
    if spec.constructor_value != "0":
        create_args += ["--value", spec.constructor_value]

    output = _cast_send(anvil, ANVIL_ACCOUNTS[0], create_args)
    for line in output.splitlines():
        if line.lower().startswith("contractaddress"):
            return line.split()[-1]
    raise SimulationError("could not determine the deployed contract address")


def _call_args(call: Call) -> list[str]:
    args = [call.signature, *call.args]
    if call.value != "0":
        args += ["--value", call.value]
    return args


def fire_concurrent(anvil: Anvil, address: str, call: Call, senders: int, gas_limit: int) -> int:
    """Sends `senders` transactions into a single block.

    Automine off, send everything, then mine once - that's what puts them in the
    same block, which is the only place a storage conflict can happen.
    """
    anvil.rpc("evm_setAutomine", "false")
    for account in ANVIL_ACCOUNTS[:senders]:
        _cast_send(
            anvil,
            account,
            ["--gas-limit", str(gas_limit), address, *_call_args(call)],
            asynchronous=True,
        )

    anvil.rpc("evm_mine")
    anvil.rpc("evm_setAutomine", "true")
    return int(_run(["cast", "block-number", "--rpc-url", anvil.rpc_url]))


def conflicts_in_block(anvil: Anvil, block_number: int, address: str) -> dict:
    """Diffs per-transaction storage writes out of the block's execution trace.

    Monad requires the tracer options object on every debug_trace* call - it is
    not optional the way it is on most EVM clients.
    """
    tracer = json.dumps({"tracer": "prestateTracer", "tracerConfig": {"diffMode": True}})
    raw = anvil.rpc("debug_traceBlockByNumber", hex(block_number), tracer)
    traces = json.loads(raw)

    target = address.lower()
    writers: dict[str, set[int]] = {}
    for index, entry in enumerate(traces):
        post = (entry.get("result") or entry).get("post") or {}
        for account, diff in post.items():
            if account.lower() != target:
                continue
            for slot in (diff.get("storage") or {}):
                writers.setdefault(slot.lower(), set()).add(index)

    contended = {slot: sorted(txs) for slot, txs in writers.items() if len(txs) > 1}
    pairs = sum(len(txs) * (len(txs) - 1) // 2 for txs in contended.values())
    return {
        "blockNumber": block_number,
        "transactionsInBlock": len(traces),
        "slotsWritten": len(writers),
        "conflictingSlots": len(contended),
        "conflictingTransactionPairs": pairs,
        "contendedSlots": contended,
    }


def simulate(source_file: str, spec: SimulationSpec, solc: str | None = None) -> dict:
    """Full loop: compile, fork, deploy, load, trace. Never raises - a failed
    simulation reports why, because "we couldn't measure it" and "we measured
    zero conflicts" must never look the same."""
    if spec.concurrent is None:
        return {"ran": False, "reason": "No concurrent call declared in the simulation spec."}

    try:
        abi_json, bytecode = compile_contract(source_file, spec.contract, solc)
        if not bytecode:
            return {"ran": False, "reason": f"{spec.contract} produced no bytecode (abstract or interface?)"}

        with Anvil(fork_url=spec.fork_url) as anvil:
            address = deploy(anvil, bytecode, spec, abi_json)
            for call in spec.setup:
                _cast_send(anvil, ANVIL_ACCOUNTS[0], [address, *_call_args(call)])

            block = fire_concurrent(anvil, address, spec.concurrent, spec.senders, spec.gas_limit)
            measurement = conflicts_in_block(anvil, block, address)

        return {
            "ran": True,
            "contract": spec.contract,
            "address": address,
            "senders": spec.senders,
            "call": spec.concurrent.signature,
            "forked": bool(spec.fork_url),
            **measurement,
        }
    except SimulationError as exc:
        return {"ran": False, "reason": str(exc)}
    except subprocess.TimeoutExpired:
        return {"ran": False, "reason": "simulation timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"ran": False, "reason": f"unexpected simulation failure: {exc}"}
