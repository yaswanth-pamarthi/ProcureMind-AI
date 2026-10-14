from decimal import Decimal, ROUND_HALF_UP

RISK_MATRIX = {
    "low": {"low": "low", "medium": "low", "high": "medium"},
    "medium": {"low": "low", "medium": "medium", "high": "high"},
    "high": {"low": "medium", "medium": "high", "high": "critical"},
}


def risk_level(likelihood, impact):
    return RISK_MATRIX[likelihood][impact]


def vendor_risk(row):
    likelihood = (
        "high"
        if row["penalty"] >= 30
        else "medium"
        if row["penalty"] > 0 or row["compliance"] == "conditional"
        else "low"
    )
    if row.get("profile_risk") == "high":
        likelihood = "high"
    impact = "high" if row["penalty"] >= 30 or row["mandatory_failure"] else "medium"
    return {"likelihood": likelihood, "impact": impact, "level": risk_level(likelihood, impact)}


def score_vendors(rows, weights):
    if not rows:
        raise ValueError("At least one submission is required")
    if len({r["currency"] for r in rows}) != 1:
        raise ValueError("Mixed currencies require an explicit conversion policy")
    if any(r["total"] <= 0 or r["delivery_days"] <= 0 for r in rows):
        raise ValueError("Price and delivery must be positive")
    if any(r.get("quality") is None for r in rows):
        raise ValueError("Missing quality history requires manual review")
    if (
        set(weights) != {"price", "quality", "delivery", "compliance", "contract"}
        or any(v < 0 for v in weights.values())
        or abs(sum(weights.values()) - 100) > 1e-6
    ):
        raise ValueError("Invalid weights")
    eligible = [r for r in rows if not r["mandatory_failure"] and r["compliance"] != "failed"]
    if not eligible:
        raise ValueError("No eligible vendor remains")
    minimum_price = min(r["total"] for r in eligible)
    minimum_days = min(r["delivery_days"] for r in eligible)
    result = []
    for r in rows:
        raw = {
            "price": r["total"],
            "delivery": r["delivery_days"],
            "quality": r["quality"],
            "compliance": {"compliant": 100, "conditional": 40, "failed": 0}[r["compliance"]],
            "contract": max(0, 100 - r["penalty"]),
        }
        norm = {
            **raw,
            "price": min(100, 100 * minimum_price / r["total"]),
            "delivery": min(100, 100 * minimum_days / r["delivery_days"]),
        }
        breakdown = [
            {
                "factor": f,
                "raw": raw[f],
                "normalized": norm[f],
                "weight": weights[f],
                "contribution": norm[f] * weights[f] / 100,
            }
            for f in weights
        ]
        total = float(
            Decimal(str(sum(b["contribution"] for b in breakdown))).quantize(
                Decimal(".01"), rounding=ROUND_HALF_UP
            )
        )
        result.append({**r, "score": total, "eligible": r in eligible, "breakdown": breakdown})
    return sorted(result, key=lambda r: (not r["eligible"], -r["score"], r["vendor_id"]))
