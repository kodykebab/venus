import Link from "next/link";

import { AuthNav } from "./AuthNav";

/**
 * Minimal navigation (style.md 25). The signed-in/signed-out half is a client
 * component so the rest of the header stays static HTML.
 */
export function SiteHeader() {
  return (
    <header className="bar">
      <div className="wrap">
        <Link className="wordmark" href="/">
          ParaCheck
        </Link>
        <nav>
          <Link href="/#how">How it works</Link>
          <Link href="/pricing">Pricing</Link>
          <AuthNav />
        </nav>
      </div>
    </header>
  );
}
