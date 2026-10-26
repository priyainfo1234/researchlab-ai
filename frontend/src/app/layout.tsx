import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ResearchLab AI",
  description: "Multi-agent research with verified, cited reports.",
};

export const viewport: Viewport = {
  themeColor: "#080910",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
