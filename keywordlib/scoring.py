"""机会分计算。"""

import math


def opportunity_score(monthly_searches: int, avg_cpc: float, competition: float) -> float:
    """机会分=40*min(1,log10(月搜索量+1)/6)+35*(1-竞争度)+25*(1/(1+CPC))，保留两位小数。"""
    volume_term = 40.0 * min(1.0, math.log10(monthly_searches + 1) / 6.0)
    competition_term = 35.0 * (1.0 - competition)
    cpc_term = 25.0 * (1.0 / (1.0 + avg_cpc))
    return round(volume_term + competition_term + cpc_term, 2)
