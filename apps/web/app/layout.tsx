import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Madar · Freight planning",
  description:
    "A reviewed, auditable freight planning workspace. Synthetic demo.",
};

export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
