export async function getUser() {
  return { id: 1, name: "alice" };
}

export async function getDashboard() {
  // Frontend client for dashboard API
  return { total: 0, active: 0 };
}
