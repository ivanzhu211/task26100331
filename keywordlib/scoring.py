"""机会分计算。"""

import math


def opportunity_score(monthly_volume: int, avg_cpc: float, competition: float) -> float:
    """按业务公式计算机会分，四舍五入到两位小数。"""
    volume_term = 40.0 * min(1.0, math.log10(monthly_volume + 1) / 6.0)
    competition_term = 35.0 * (1.0 - competition)
    cpc_term = 25.0 * (1.0 / (1.0 + avg_cpc))
    return round(volume_term + competition_term + cpc_term, 2)
