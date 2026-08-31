import { requestAnalysisResult } from "./lib/apiClient";

export const useAnalysisResult = (symbol: string) => requestAnalysisResult(symbol);
