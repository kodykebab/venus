import { Container, ContainerProxy } from "@cloudflare/containers";

export { ContainerProxy };

/**
 * The analyzer container: Foundry, solc, Slither and the ParaCheck analyzer.
 *
 * This is the only part of the system that touches customer source, and running
 * a scan means running the repository's own build system - `forge install` runs
 * git hooks, `npm install` runs postinstall scripts. Both are arbitrary code
 * execution by design, so this container is configured as though an attacker
 * already has execution inside it.
 *
 * The egress allowlist is the control we could never get on an ordinary
 * container host. Internet access is off by default here; only the hosts a
 * Solidity toolchain genuinely needs are reachable. A postinstall script that
 * reads a secret can no longer POST it anywhere of its own choosing - it has
 * nowhere to send it.
 */
export class Analyzer extends Container {
  // Long enough to fetch dependencies, compile and analyse a real project.
  defaultPort = 8080;
  sleepAfter = "15m";

  // Off by default. Everything reachable is named below.
  enableInternet = false;

  allowedHosts = [
    // Cloning the repository under review, and fetching dependencies that are
    // git repos - which is how Foundry libraries work.
    "github.com",
    "api.github.com",
    "codeload.github.com",
    "*.githubusercontent.com",
    "objects.githubusercontent.com",
    // release-hosted binaries: solc via svm, forge-std tarballs
    "release-assets.githubusercontent.com",
    "binaries.soliditylang.org",
    "solc-bin.ethereum.org",
    // Hardhat and Truffle projects
    "registry.npmjs.org",
  ];

  // Nothing in a scan should reach cloud metadata. Denied explicitly as well as
  // being absent from the allowlist, because deniedHosts is evaluated first and
  // a future widening of the allowlist must not silently re-expose these.
  deniedHosts = [
    "169.254.169.254",
    "metadata.google.internal",
    "*.internal",
  ];

  override onStart() {
    console.log("analyzer: container started");
  }

  override onError(error: unknown) {
    // A crashed container must not take the queue consumer down with it; the
    // scan is marked failed by the consumer's catch.
    console.error("analyzer: container error", error);
    throw error;
  }
}
