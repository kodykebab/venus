/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: the marketing pages are HTML with no server behind them, and
  // the dashboard is a client component that talks to the Worker API directly.
  // style.md 46 asks the marketing site to embody the product's own philosophy -
  // fast, minimal JavaScript, static-first - and this is the shape that does it.
  // It also means Cloudflare Pages serves plain assets with no SSR adapter.
  output: "export",
  reactStrictMode: true,
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
