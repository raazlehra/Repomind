import { useAnalysisResult } from "../../hooks";
import { buildOptionChainModel } from "../../lib/optionChainModel";

export function useOptionChainModel(symbol: string) {
  const result = useAnalysisResult(symbol);
  return buildOptionChainModel(result);
}
