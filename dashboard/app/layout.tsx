import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Triage — failure root-cause analysis for coding agents",
  description:
    "Ingests a failed coding-agent run, classifies the failure mode, produces an evidence-grounded root-cause hypothesis, and emits a reusable playbook card.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;650;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
