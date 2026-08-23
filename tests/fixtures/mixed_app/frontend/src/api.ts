export async function createPayment(amount: number): Promise<boolean> {
  const response = await fetch('/payments', { method: 'POST', body: JSON.stringify({ amount }) });
  return response.ok;
}
