import { MarketBiasCard } from "../components/MarketBiasCard";
import { useOptionChainModel } from "./optionchain/useOptionChainModel";

export function OptionChain() {
  const model = useOptionChainModel("NIFTY");
  return <MarketBiasCard model={model} />;
}
