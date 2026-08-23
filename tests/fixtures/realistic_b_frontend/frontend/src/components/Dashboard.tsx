import React from "react";
import { fetchDashboard } from "../api";

export function Dashboard() {
  const data = fetchDashboard();
  return <div>Widgets: {data.widgets.length}</div>;
}
