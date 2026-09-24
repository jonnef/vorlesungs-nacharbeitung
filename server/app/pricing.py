"""Preise (USD pro 1 Mio. Tokens, Stand 2026) und Kostenberechnung.

Die Batch-API kostet 50 % des Standardpreises. Vor dem Einsatz eines anderen Modells
die Preise unter https://claude.com/pricing prüfen und hier ergänzen.
"""

PRICES = {
    # Modell: (Input, Output)
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
}
CACHE_WRITE_FACTOR = 1.25
CACHE_READ_FACTOR = 0.10
BATCH_FACTOR = 0.50


def prices_for(model: str) -> tuple[float, float]:
    if model not in PRICES:
        raise ValueError(f"Kein Preis für Modell {model!r} hinterlegt (app/pricing.py).")
    return PRICES[model]


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    batch: bool = True,
) -> float:
    p_in, p_out = prices_for(model)
    total = (
        input_tokens * p_in
        + cache_creation_tokens * p_in * CACHE_WRITE_FACTOR
        + cache_read_tokens * p_in * CACHE_READ_FACTOR
        + output_tokens * p_out
    ) / 1_000_000
    return total * (BATCH_FACTOR if batch else 1.0)


def worst_case_usd(model: str, input_tokens: int, max_output_tokens: int) -> float:
    """Obergrenze: alle Input-Tokens + voll ausgeschöpftes max_tokens (inkl. Denkprozess)."""
    return cost_usd(model, input_tokens, max_output_tokens)
