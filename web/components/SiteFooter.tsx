import Link from "next/link";

export function SiteFooter() {
  return (
    <footer>
      <div className="wrap">
        <span>ParaCheck</span>
        <span className="spacer" />
        <Link href="/pricing">Pricing</Link>
        <Link href="/enterprise">Enterprise</Link>
        <a href="https://github.com/kodyshan/paracheck">Source</a>
      </div>
    </footer>
  );
}
