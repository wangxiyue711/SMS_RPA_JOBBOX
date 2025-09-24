import React from "react";
import Sidebar from "../components/Sidebar";
import Header from "../components/Header";
import dynamic from "next/dynamic";

const DashboardClient = dynamic(() => import("./DashboardClient"), {
  ssr: false,
});

export default function DashboardPage() {
  return (
    <div>
      <Header />
      <div style={{ padding: 28 }}>
        <div className="dashboard">
          <Sidebar heading={"HOME"} />
          <DashboardClient />
        </div>
      </div>
    </div>
  );
}
