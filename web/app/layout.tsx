import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ParaCheck | Ship cheaper contracts",
  description: "Evidence-driven optimization for Solidity contracts.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
