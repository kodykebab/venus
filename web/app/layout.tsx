import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import { Providers } from "@/components/Providers";

import { SiteFooter } from "@/components/SiteFooter";
import "./globals.css";

// Self-hosted by next/font at build time: no render-blocking request to Google,
// and no third-party script on a page that is meant to be fast (style.md 46).
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  variable: "--font-sans",
  display: "swap",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://paracheck.dev"),
  title: {
    default: "ParaCheck - ship cheaper contracts",
    template: "%s - ParaCheck",
  },
  description:
    "ParaCheck finds the storage, execution and parallelism patterns making your Solidity expensive, and shows you exactly what to change.",
  openGraph: {
    type: "website",
    siteName: "ParaCheck",
    title: "ParaCheck - ship cheaper contracts",
    description:
      "Find the storage, execution and parallelism patterns making your Solidity expensive.",
  },
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "light dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <Providers>
          {children}
          <SiteFooter />
        </Providers>
      </body>
    </html>
  );
}
