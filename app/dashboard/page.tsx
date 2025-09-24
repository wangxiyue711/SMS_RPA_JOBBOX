import React from "react";
import dynamic from "next/dynamic";

const DashboardClient = dynamic(() => import("./DashboardClient"), {
  ssr: false,
});

export default function DashboardPage() {
  return (
    <div style={{ padding: 28 }}>
      <DashboardClient />
    </div>
  );
}
