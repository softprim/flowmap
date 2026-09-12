"""Fluxul de comandă: intrare (coș) -> ieșire (factură)."""
from .catalog import get_product, in_stock
from .pricing import add_vat, apply_discount, line_total


class Order:
    def __init__(self, customer: str):
        self.customer = customer
        self.lines: list[dict] = []

    def add(self, sku: str, qty: int) -> None:
        product = get_product(sku)
        if not in_stock(product, qty):
            raise RuntimeError(f"stoc insuficient pentru {sku}")
        self.lines.append({"sku": sku, "qty": qty, "total": line_total(product["price"], qty)})

    def subtotal(self) -> float:
        return round(sum(l["total"] for l in self.lines), 2)


def build_invoice(order: Order, discount_code: str | None = None) -> dict:
    sub = order.subtotal()
    after_discount = apply_discount(sub, discount_code)
    total = add_vat(after_discount)
    return {"customer": order.customer, "subtotal": sub, "discount_code": discount_code, "total": total}


def validate_invoice(invoice: dict) -> dict:
    if invoice["total"] < 0:
        raise AssertionError(f"total negativ pe factură: {invoice['total']}")
    return invoice
