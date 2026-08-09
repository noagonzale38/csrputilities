import type { Metadata } from "next";
import { Manrope } from "next/font/google";
import "./globals.css";

const manrope = Manrope({ subsets: ["latin"], display: "swap" });

function dashboardEnvironmentLabel() {
  const dashboardEnv = process.env.DASHBOARD_ENV?.trim().toLowerCase();

  if (dashboardEnv === "staging") return "Staging";
  if (dashboardEnv === "development" || dashboardEnv === "dev") return "Development";
  return "";
}

export const metadata: Metadata = {
  title: "CSRP Utilities",
  description: "Discord bot dashboard and staff control panel",
  icons: {
    icon: "https://csrptickets-storage.s3.us-east-1.amazonaws.com/018b50d0d885271446f02f157fe8e00a.png"
  }
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const environmentLabel = dashboardEnvironmentLabel();

  return (
    <html lang="en">
      <body className={manrope.className}>
        {environmentLabel && <div className="environment-banner">{environmentLabel}</div>}
        {children}
      </body>
    </html>
  );
}
