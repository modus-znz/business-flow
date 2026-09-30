"""Inventory economics (stockpyl EOQ) + shipment packing (ortools CP-SAT).

Assumptions are parameters, never buried: order cost K, holding rate, demand
cycles/year, pallet capacity. Weights parse from descriptions (GR/KG/ML/CL),
median-piece fallback for the rest.
"""
import math
import re

W = re.compile(r"\b(GR|KG|ML|LT|CL)\.? ?(\d+)\b")
G = {"GR": 1, "ML": 1, "KG": 1000, "LT": 1000, "CL": 10}


def attach_weights(items, packaging=1.05):
    parsed = []
    for r in items:
        m = W.search(r.get("descrizione", "") or "")
        if m and r.get("qty") and r.get("mpl"):
            g = int(m.group(2)) * G[m.group(1)]
            r["kg"] = r["qty"] * r["mpl"] * g / 1000 * packaging
            parsed.append(r)
        else:
            r["kg"] = None
    if parsed:
        med = sorted(p["kg"] / (p["qty"] * p["mpl"]) for p in parsed)[len(parsed) // 2]
        for r in items:
            if r["kg"] is None and r.get("qty") and r.get("mpl"):
                r["kg"] = r["qty"] * r["mpl"] * med
    return len(parsed)


def eoq_table(items, order_cost=450.0, holding_rate=0.25, cycles_per_year=12, top=5):
    from stockpyl.eoq import economic_order_quantity

    rows = []
    for r in sorted(items, key=lambda r: -(r.get("total") or 0))[:top]:
        if not (r.get("qty") and r.get("price")):
            continue
        demand = r["qty"] * cycles_per_year
        q, _ = economic_order_quantity(
            fixed_cost=order_cost,
            holding_cost=holding_rate * r["price"],
            demand_rate=demand)
        rows.append({"descrizione": r["descrizione"], "qty": r["qty"],
                     "eoq": round(q, 1), "orders_per_year": round(demand / q, 1)})
    return rows


def pack_pallets(items, cap_kg=450, time_limit=15):
    """Min pallets, SKUs unsplit. Returns (count, loads, status)."""
    from ortools.sat.python import cp_model

    w = [math.ceil(r["kg"]) for r in items if r.get("kg")]
    bins = []
    for it in sorted(w, reverse=True):  # FFD upper bound
        for i, b in enumerate(bins):
            if b + it <= cap_kg:
                bins[i] += it
                break
        else:
            bins.append(it)
    ub = len(bins)

    m = cp_model.CpModel()
    x = {(i, b): m.new_bool_var(f"x{i}_{b}")
         for i in range(len(w)) for b in range(ub)}
    y = [m.new_bool_var(f"y{b}") for b in range(ub)]
    for i in range(len(w)):
        m.add_exactly_one(x[i, b] for b in range(ub))
    for b in range(ub):
        m.add(sum(w[i] * x[i, b] for i in range(len(w))) <= cap_kg * y[b])
        if b:
            m.add(y[b] <= y[b - 1])
    m.minimize(sum(y))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    status = s.solve(m)
    loads = sorted((sum(w[i] for i in range(len(w)) if s.value(x[i, b]))
                    for b in range(ub)), reverse=True)
    return int(s.objective_value), [l for l in loads if l], s.status_name(status)
