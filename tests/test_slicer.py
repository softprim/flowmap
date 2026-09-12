from flowmap import slicer


def fn(trace, ids):
    return {trace["calls"][i]["func"] for i in ids}


def test_subtree_is_transaction(trace):
    bogdan = [c for c in trace["calls"] if c["func"] == "process"][1]["id"]
    st = slicer.subtree(trace, bogdan)
    assert fn(trace, st) == {"process", "Order.__init__", "Order.add", "get_product", "in_stock", "line_total",
                             "build_invoice", "Order.subtotal", "apply_discount", "add_vat", "validate_invoice"}
    assert all(i >= bogdan for i in st)


def test_backward_slice_reaches_the_computation(trace):
    bad = [c for c in trace["calls"] if c["func"] == "validate_invoice" and c["exc"]][0]["id"]
    back = slicer.backward_slice(trace, bad)
    assert fn(trace, back) == {"validate_invoice", "process", "main", "build_invoice", "Order.subtotal", "apply_discount", "add_vat"}
    assert "Order.add" not in fn(trace, back)  # nu a produs valoarea, nu intră în felie
    text = slicer.describe(trace, back)
    assert "apply_discount(total=18.5, code='FIX50') -> -31.5" in text and "!! AssertionError" in text


def test_forward_slice_follows_consumers(trace):
    sub = [c for c in trace["calls"] if c["func"] == "Order.subtotal"][1]["id"]
    fwd = slicer.forward_slice(trace, sub)
    assert fn(trace, fwd) == {"Order.subtotal", "apply_discount", "add_vat"}


def test_full_slice_and_errors(trace):
    assert slicer.full_slice(trace, 0) == set(range(len(trace["calls"])))
    import pytest
    with pytest.raises(IndexError):
        slicer.subtree(trace, 10_000)
