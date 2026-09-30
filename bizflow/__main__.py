"""bizflow CLI.

  bizflow process  <pdf>   header JSON + line-item CSV/Parquet + summary
  bizflow analyze  <csv>   duckdb reconciliation, brands, top items
  bizflow optimize <csv>   EOQ table + optimal pallet packing
  bizflow convert  <file>  anything -> Markdown
  bizflow ocr <in> <out>   scanned/mixed PDF -> searchable PDF/A
"""
import argparse
import csv
import json
import sys
from pathlib import Path

PKG = Path(__file__).parent
DEFAULT_LAYOUT = PKG / "layouts" / "it.sample-vendor.yml"
USER_TEMPLATES = Path.home() / ".local/share/invoice2data-templates"


def _read_items(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            for k in ("qty", "price", "total", "piece_price", "kg"):
                if r.get(k):
                    r[k] = float(r[k])
                elif k in r:
                    r[k] = None
            if r.get("mpl"):
                r["mpl"] = int(float(r["mpl"]))
            rows.append(r)
    return rows


def cmd_process(a):
    from . import analyze, extract

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(a.pdf).stem

    tdir = Path(a.templates) if a.templates else (
        USER_TEMPLATES if USER_TEMPLATES.is_dir() else PKG.parent / "templates")
    header = extract.extract_header(a.pdf, tdir)
    if header:
        header = {k: str(v) for k, v in header.items()}
        (out / f"{stem}-header.json").write_text(json.dumps(header, indent=2))
        print(f"header : {header.get('issuer')} n.{header.get('invoice_number')} "
              f"{header.get('date')} {header.get('amount')} {header.get('currency')}")
    else:
        print("header : no invoice2data template matched (add one under "
              f"{tdir})", file=sys.stderr)

    items = extract.harvest_items(a.pdf, extract.load_layout(a.layout))
    if not items:
        sys.exit("no line items found - check the layout spec")
    csv_path = out / f"{stem}-items.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=items[0].keys())
        w.writeheader()
        w.writerows(items)
    print(f"items  : {len(items)} rows -> {csv_path}")
    print(analyze.render(analyze.summarize(csv_path, out / f"{stem}-items.parquet")))


def cmd_analyze(a):
    from . import analyze

    print(analyze.render(analyze.summarize(a.csv, a.parquet)))


def cmd_optimize(a):
    from . import optimize

    items = _read_items(a.csv)
    n = optimize.attach_weights(items)
    kg = sum(r["kg"] for r in items if r.get("kg"))
    print(f"weights: {n}/{len(items)} parsed from descriptions; "
          f"shipment ~{kg:,.0f} kg")
    print(f"\nEOQ (K={a.order_cost}, holding={a.holding:.0%}/yr, "
          f"{a.cycles} cycles/yr):")
    for r in optimize.eoq_table(items, a.order_cost, a.holding, a.cycles):
        print(f"  {r['descrizione'][:40]:<42} qty {r['qty']:>5.0f}  "
              f"EOQ {r['eoq']:>7.1f}  orders/yr {r['orders_per_year']:>4.1f}")
    count, loads, status = optimize.pack_pallets(items, a.pallet_cap)
    print(f"\npallets: {count} @ {a.pallet_cap} kg [{status}] loads={loads}")


def cmd_convert(a):
    from . import convert

    md = convert.to_markdown(a.src, a.out)
    print(a.out if a.out else md)


def cmd_ocr(a):
    from . import convert

    convert.ocr(a.src, a.dst, lang=a.lang)
    print(f"ocr    : {a.dst} (searchable PDF/A, lang={a.lang})")


def main():
    p = argparse.ArgumentParser(prog="bizflow", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("process")
    s.add_argument("pdf")
    s.add_argument("--layout", default=str(DEFAULT_LAYOUT))
    s.add_argument("--templates")
    s.add_argument("--out", default="bizflow-out")
    s.set_defaults(fn=cmd_process)

    s = sub.add_parser("analyze")
    s.add_argument("csv")
    s.add_argument("--parquet")
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("optimize")
    s.add_argument("csv")
    s.add_argument("--pallet-cap", type=int, default=450)
    s.add_argument("--order-cost", type=float, default=450.0)
    s.add_argument("--holding", type=float, default=0.25)
    s.add_argument("--cycles", type=int, default=12)
    s.set_defaults(fn=cmd_optimize)

    s = sub.add_parser("convert")
    s.add_argument("src")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_convert)

    s = sub.add_parser("ocr")
    s.add_argument("src")
    s.add_argument("dst")
    s.add_argument("--lang", default="ita+eng")
    s.set_defaults(fn=cmd_ocr)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
