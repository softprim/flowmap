"""
Feliere dinamică peste un trace (implementare de referință, oglindită în viewer/index.html).

  subtree(t, id)         toate apelurile din subarborele apelului `id` (tranzacția lui)
  backward_slice(t, id)  de unde vin datele: strămoșii, producătorii valorilor primite ca argument
                         (cu calculul din interiorul lor și strămoșii lor), tranzitiv
  forward_slice(t, id)   unde ajung datele: descendenții și consumatorii valorii returnate, tranzitiv
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

Trace = dict[str, Any]


def _calls(t: Trace) -> list[dict]:
    return t["calls"]


def subtree(t: Trace, root_id: int) -> set[int]:
    calls = _calls(t)
    if not 0 <= root_id < len(calls):
        raise IndexError(f"apel inexistent: {root_id}")
    out = {root_id}
    for c in calls[root_id + 1 :]:
        if c["parent"] is not None and c["parent"] in out:
            out.add(c["id"])
    return out


def ancestors(t: Trace, call_id: int) -> list[int]:
    calls = _calls(t)
    out, p = [], calls[call_id]["parent"]
    while p is not None:
        out.append(p)
        p = calls[p]["parent"]
    return out


def backward_slice(t: Trace, call_id: int) -> set[int]:
    calls = _calls(t)
    producers: dict[int, list[int]] = defaultdict(list)
    for d in t.get("data_edges", []):
        producers[d["to"]].append(d["from"])
    out: set[int] = set()
    queue = [call_id]
    while queue:
        i = queue.pop()
        if i in out:
            continue
        out.add(i)
        if calls[i]["parent"] is not None:
            queue.append(calls[i]["parent"])
        for p in producers.get(i, ()):
            queue.append(p)
            queue.extend(subtree(t, p))
            queue.extend(a for a in ancestors(t, p) if a not in out)
    return out


def forward_slice(t: Trace, call_id: int) -> set[int]:
    consumers: dict[int, list[int]] = defaultdict(list)
    for d in t.get("data_edges", []):
        consumers[d["from"]].append(d["to"])
    out: set[int] = set()
    queue = [call_id]
    while queue:
        i = queue.pop()
        if i in out:
            continue
        out.add(i)
        out.update(subtree(t, i))
        queue.extend(consumers.get(i, ()))
    return out


def full_slice(t: Trace, call_id: int) -> set[int]:
    return backward_slice(t, call_id) | forward_slice(t, call_id)


def describe(t: Trace, ids: set[int]) -> str:
    """Rezumat text al unei felii, în ordine temporală, indentat după adâncime."""
    calls = _calls(t)
    depth: dict[int, int] = {}
    lines = []
    for i in sorted(ids):
        c = calls[i]
        d = depth[c["parent"]] + 1 if c["parent"] in depth else 0
        depth[i] = d
        args = ", ".join(f"{k}={v}" for k, v in c["args"].items() if k != "self")
        if c["exc"] is None:
            tail = f" -> {c['ret']}"
        else:
            tail = f" !! {c['exc']['type']}: {c['exc']['msg']}" + (" (tratată aici)" if c["exc"].get("handled") else "")
        lines.append(f"{'  ' * d}#{i} {c['func']}({args}){tail}   [{c['file']}:{c['line']}]")
    return "\n".join(lines)
