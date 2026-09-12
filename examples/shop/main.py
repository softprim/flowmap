"""Punct de intrare: simulează trei comenzi, una cu bug logic, una cu stoc lipsă."""
from shop.orders import Order, build_invoice, validate_invoice


def process(customer: str, items: list[tuple[str, int]], code: str | None) -> dict | None:
    order = Order(customer)
    try:
        for sku, qty in items:
            order.add(sku, qty)
        invoice = validate_invoice(build_invoice(order, code))
        print(f"OK   {customer}: total {invoice['total']}")
        return invoice
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {customer}: {type(e).__name__}: {e}")
        return None


def main():
    process("Ana", [("SKU-100", 3), ("SKU-200", 1)], "WELCOME10")
    process("Bogdan", [("SKU-100", 1)], "FIX50")      # bug: total negativ
    process("Carmen", [("SKU-300", 2)], None)         # stoc 0 -> RuntimeError


if __name__ == "__main__":
    main()
