from fastapi import APIRouter

from backend.analysis import generate_analysis_result

router = APIRouter()


@router.get("/analysis/{symbol}")
def option_chain_analysis(symbol: str) -> dict[str, object]:
    return generate_analysis_result(symbol)
