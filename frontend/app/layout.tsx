import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Agentic SRE Copilot",
  description: "Autonomous incident investigation and remediation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
