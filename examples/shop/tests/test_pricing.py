from shop.pricing import apply_discount, line_total


def test_line_total():
    assert line_total(18.5, 3) == 55.5


def test_welcome_discount():
    assert apply_discount(100.0, "WELCOME10") == 90.0


def test_fixed_discount_never_negative():
    assert apply_discount(10.0, "FIX50") >= 0
