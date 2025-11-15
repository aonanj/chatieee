import "./globals.css";
import localFont from "next/font/local";

const appSans = localFont({
  src: [
    { path: "../public/fonts/inter-v20-latin-regular.woff2", weight: "400", style: "normal" },
    { path: "../public/fonts/inter-v20-latin-italic.woff2", weight: "400", style: "italic" },
    { path: "../public/fonts/inter-v20-latin-500.woff2", weight: "500", style: "normal" },
    { path: "../public/fonts/inter-v20-latin-500italic.woff2", weight: "500", style: "italic" },
    { path: "../public/fonts/inter-v20-latin-600.woff2", weight: "600", style: "normal" },
    { path: "../public/fonts/inter-v20-latin-600italic.woff2", weight: "600", style: "italic" },
    { path: "../public/fonts/inter-v20-latin-700.woff2", weight: "700", style: "normal" },
    { path: "../public/fonts/inter-v20-latin-700italic.woff2", weight: "700", style: "italic" },
    { path: "../public/fonts/inter-v20-latin-800.woff2", weight: "800", style: "normal" },
    { path: "../public/fonts/inter-v20-latin-800italic.woff2", weight: "800", style: "italic" },
    { path: "../public/fonts/inter-v20-latin-900.woff2", weight: "900", style: "normal" },
    { path: "../public/fonts/inter-v20-latin-900italic.woff2", weight: "900", style: "italic" },
  ],
  display: "swap",
});


export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
        <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png" />
        <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png" />
        <link rel="manifest" href="/site.webmanifest" />
      </head>
      <body
        className={`${appSans.className} app-shell min-h-screen text-gray-900`}
      >
        {children}
      </body>
    </html>
  );
}
