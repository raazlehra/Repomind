
import { getDashboard } from "../apiClient";

export default function Dashboard() {
  async function load() {
    const data = await getDashboard();
    console.log("dashboard", data);
  }
  return "Dashboard";
}
