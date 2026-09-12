"""Catalog de produse (sursa de date)."""

PRODUCTS = {
    "SKU-100": {"name": "Priză Living Light", "price": 18.50, "stock": 40},
    "SKU-200": {"name": "Întrerupător cap-scară", "price": 22.00, "stock": 12},
    "SKU-300": {"name": "Ramă 3 module", "price": 9.90, "stock": 0},
}


def get_product(sku: str) -> dict:
    return dict(PRODUCTS[sku])


def in_stock(product: dict, qty: int) -> bool:
    return product["stock"] >= qty
