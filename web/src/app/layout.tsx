import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Book2Video",
  description: "Book to Video workflow tool",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="font-sans antialiased min-h-screen">{children}</body>
    </html>
  );
}
