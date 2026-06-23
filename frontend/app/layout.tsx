import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ZeroWall — DGX Spark MTD Console",
  description: "Generative AI firewall operator dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
