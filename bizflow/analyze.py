"""DuckDB analysis over harvested line items: reconciliation, brands, Parquet."""
import duckdb


def summarize(csv_path, parquet_out=None):
    con = duckdb.connect()
    con.execute(f"CREATE TABLE items AS SELECT * FROM read_csv_auto('{csv_path}')")
    has_precision = all(
        c in [d[0] for d in con.execute("DESCRIBE items").fetchall()]
        for c in ("qty", "mpl", "piece_price"))

    out = {}
    row = con.execute(
        "SELECT count(*), round(sum(total),2) FROM items").fetchone()
    out["items"], out["printed_sum"] = row
    if has_precision:
        out["full_precision_sum"] = con.execute(
            "SELECT round(sum(qty*mpl*piece_price),2) FROM items").fetchone()[0]
        out["rounding_drift"] = round(
            out["printed_sum"] - out["full_precision_sum"], 2)
    out["brands"] = con.execute("""
        SELECT split_part(descrizione,' ',1) AS brand, count(*) AS skus,
               round(sum(total),2) AS value,
               round(100*sum(total)/(SELECT sum(total) FROM items),1) AS pct
        FROM items GROUP BY 1 ORDER BY value DESC LIMIT 5""").fetchall()
    out["top_items"] = con.execute(
        "SELECT code, descrizione, total FROM items "
        "ORDER BY total DESC LIMIT 3").fetchall()
    if parquet_out:
        con.execute(f"COPY items TO '{parquet_out}'")
        out["parquet"] = str(parquet_out)
    return out


def render(out):
    lines = [f"line items : {out['items']}",
             f"printed sum: {out['printed_sum']:,.2f}"]
    if "full_precision_sum" in out:
        lines.append(f"full-precision sum: {out['full_precision_sum']:,.2f} "
                     f"(rounding drift {out['rounding_drift']:+.2f})")
    lines.append("top brands : " + ", ".join(
        f"{b} {v:,.0f} ({p}%)" for b, _, v, p in out["brands"]))
    lines.append("top items  : " + "; ".join(
        f"{d[:40]} {t:,.2f}" for _, d, t in out["top_items"]))
    if "parquet" in out:
        lines.append(f"parquet    : {out['parquet']}")
    return "\n".join(lines)
