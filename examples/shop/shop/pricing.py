"""Reguli de preț și discount."""


def line_total(price: float, qty: int) -> float:
    return round(price * qty, 2)


def apply_discount(total: float, code: str | None) -> float:
    if code is None:
        return total
    if code == "WELCOME10":
        return round(total * 0.9, 2)
    if code.startswith("FIX"):
        # BUG intenționat: discountul fix se scade fără limită inferioară,
        # totalul poate deveni negativ (valoare în afara domeniului contractual)
        amount = float(code[3:])
        return round(total - amount, 2)
    raise ValueError(f"cod de discount necunoscut: {code}")


def add_vat(total: float, rate: float = 0.19) -> float:
    return round(total * (1 + rate), 2)
