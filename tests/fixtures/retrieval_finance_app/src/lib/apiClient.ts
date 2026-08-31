export async function requestAnalysisResult(symbol: string) {
  return fetch(`/api/analysis/${symbol}`).then((response) => response.json());
}
