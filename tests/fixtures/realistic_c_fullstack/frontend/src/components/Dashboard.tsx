import { getDashboard } from "../apiClient";

export default function Dashboard() {
  // Simplified component that uses the API client
  async function load() {
    const data = await getDashboard();
    console.log("dashboard", data);
  }

  return "Dashboard component";
}
