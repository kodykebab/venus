import { JsonRpcProvider } from "ethers";

/**
 * Monad returns `-32602 Invalid params` if the tracer-options object is omitted from a
 * debug_trace* call - unlike most EVM clients, where it's optional. TracerConfig is a
 * required parameter (not `?`) on every method below so a call site can never compile
 * without one.
 */
export interface TracerConfig {
  tracer: "prestateTracer" | "callTracer";
  tracerConfig?: {
    diffMode?: boolean;
    onlyTopCall?: boolean;
    withLog?: boolean;
  };
}

export class RpcClient {
  readonly provider: JsonRpcProvider;

  constructor(rpcUrl: string) {
    this.provider = new JsonRpcProvider(rpcUrl);
  }

  async traceBlockByNumber(blockNumber: number, tracerConfig: TracerConfig): Promise<unknown> {
    const blockTag = "0x" + blockNumber.toString(16);
    return this.provider.send("debug_traceBlockByNumber", [blockTag, tracerConfig]);
  }

  async traceTransaction(txHash: string, tracerConfig: TracerConfig): Promise<unknown> {
    return this.provider.send("debug_traceTransaction", [txHash, tracerConfig]);
  }

  async getBlockNumber(): Promise<number> {
    return this.provider.getBlockNumber();
  }
}

export const PRESTATE_DIFF_TRACER: TracerConfig = {
  tracer: "prestateTracer",
  tracerConfig: { diffMode: true },
};
