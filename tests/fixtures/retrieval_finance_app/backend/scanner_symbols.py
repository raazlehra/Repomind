NIFTY_SYMBOLS = ["NIFTY", "BANKNIFTY"]
FNO_SYMBOLS = ["RELIANCE", "TCS", "INFY"]


def load_scanner_symbols() -> list[str]:
    """Load configured scanner symbols."""
    return [*NIFTY_SYMBOLS, *FNO_SYMBOLS]
