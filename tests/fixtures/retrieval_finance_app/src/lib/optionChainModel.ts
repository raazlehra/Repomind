import { calculateConfidence } from "./confidence/calculateConfidence";

export function buildOptionChainModel(chain: unknown) {
  const confidence = calculateConfidence(chain);
  return {
    recommendationLabel: confidence.label,
    bullishConfluenceScore: confidence.score,
  };
}
