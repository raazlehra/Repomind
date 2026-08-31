from backend.scanner_symbols import load_scanner_symbols


def load_stock_universe_for_scanner() -> list[str]:
    symbols = load_scanner_symbols()
    return sorted(symbols)
