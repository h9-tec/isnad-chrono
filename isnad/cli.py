"""CLI: python -m isnad.cli fetch <rawis|books|run|status>."""

import argparse

import httpx

from isnad import build, fetch

DB = "data/queue.sqlite"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="isnad")
    ap.add_argument("--db", default=DB)
    top = ap.add_subparsers(dest="cmd", required=True)
    f = top.add_parser("fetch").add_subparsers(dest="sub", required=True)
    f.add_parser("rawis")
    b = f.add_parser("books")
    b.add_argument("--book")
    b.add_argument("--force", action="store_true", help="re-enumerate books already done")
    f.add_parser("retry-errors")
    r = f.add_parser("run")
    r.add_argument("--kind", choices=["rawi", "hadith"], required=True)
    r.add_argument("--book")
    r.add_argument("--fetcher", choices=["firecrawl", "local"], default="local")
    r.add_argument("--limit", type=int)
    r.add_argument("--include-passages", action="store_true")
    s = f.add_parser("status")
    s.add_argument("--kind")
    s.add_argument("--book")
    bp = top.add_parser("build")
    bp.add_argument("--kind", choices=["rawi", "hadith", "all"], default="all")
    bp.add_argument("--cache-root", default="data/raw/html")
    bp.add_argument("--out-dir", default="data")
    sp = top.add_parser("score")
    sp.add_argument("--edges", default="data/edges.parquet")
    sp.add_argument("--rawi", default="data/rawi.parquet")
    sp.add_argument("--denials", help="parquet/csv with student_id,teacher_id")
    sp.add_argument("--out", default="data/edge_scores.parquet")
    gp = top.add_parser("gold")
    gp.add_argument("--rawi", default="data/rawi.parquet")
    gp.add_argument("--tuhfa", default="data/tuhfa.parquet")
    gp.add_argument("--marasil", default="gold/marasil_pairs.json")
    gp.add_argument("--out-dir", default="data")
    vp = top.add_parser("validate")
    vp.add_argument("--scores", default="data/edge_scores.parquet")
    vp.add_argument("--rawi", default="data/rawi.parquet")
    vp.add_argument("--hadith", default="data/hadith.parquet")
    vp.add_argument("--denials-marasil", default="data/denials_marasil.parquet")
    vp.add_argument("--denials-tuhfa", default="data/denials_tuhfa.parquet")
    vp.add_argument("--out", default="data/metrics.json")
    vp.add_argument("--figures", default="figures")
    rp = top.add_parser("report")
    rp.add_argument("--scores", default="data/edge_scores.parquet")
    rp.add_argument("--rawi", default="data/rawi.parquet")
    rp.add_argument("--hadith", default="data/hadith.parquet")
    rp.add_argument("--db", dest="report_db", default=DB)
    rp.add_argument("--out-dir", default="data")
    rp.add_argument("--n", type=int, default=50)
    args = ap.parse_args(argv)

    if args.cmd == "report":
        import os

        from isnad import report
        db = args.report_db if args.report_db and os.path.exists(args.report_db) else None
        print(report.run_report_files(args.scores, args.rawi, args.hadith, db,
                                      args.out_dir, args.n))
        return

    if args.cmd == "validate":
        from isnad import validate
        m = validate.run_validate(args.scores, args.rawi, args.hadith,
                                  {"marasil": args.denials_marasil, "tuhfa": args.denials_tuhfa},
                                  args.out, args.figures)
        print({k: v for k, v in m.items() if k != "verdict_counts_by_book"})
        return

    if args.cmd == "gold":
        from isnad import gold
        gold.run_gold(args.rawi, args.tuhfa, args.marasil, args.out_dir)
        return

    if args.cmd == "score":
        import pandas as pd

        from isnad import score
        den = set()
        if args.denials:
            d = (pd.read_csv(args.denials) if args.denials.endswith(".csv")
                 else pd.read_parquet(args.denials))
            d = d.dropna(subset=["student_id", "teacher_id"])
            den = {(int(a), int(b)) for a, b in zip(d["student_id"], d["teacher_id"])}
        df = score.score_edges(args.edges, args.rawi, den, args.out)
        print(df["verdict"].value_counts().to_dict())
        return

    if args.cmd == "build":
        out = args.out_dir
        if args.kind in ("rawi", "all"):
            build.build_rawi(args.cache_root, f"{out}/rawi.parquet")
        if args.kind in ("hadith", "all"):
            build.build_hadith(args.cache_root, f"{out}/hadith.parquet", f"{out}/edges.parquet",
                               reset=args.kind == "hadith")
        return

    queue = fetch.Queue(args.db)
    if args.sub == "retry-errors":
        print(f"reset {queue.reset_errors()} error rows to pending")
        return
    if args.sub == "status":
        print(queue.counts_by(args.kind, args.book))
        return
    with httpx.Client(timeout=30) as client:
        local = fetch.LocalFetcher(client)
        if args.sub == "rawis":
            n = 0
            for url, id in fetch.load_rawi_sitemap(local):
                queue.add(url, "rawi", id=id)
                n += 1
            print(f"rawi urls: {n}")
        elif args.sub == "books":
            failed = []
            for book in [args.book] if args.book else fetch.list_books(local):
                if queue.book_done(book) and not args.force:
                    print(book, "done, skipping", flush=True)
                    continue
                try:
                    res = fetch.enumerate_book(local, queue, book)
                except Exception as e:  # keep going; report at the end
                    failed.append((book, repr(e)))
                    queue.mark_book(book, "failed")
                    print(book, "FAILED", repr(e), flush=True)
                    continue
                queue.mark_book(book, "done", res.found, res.expected)
                warn = f"  WARNING shortfall {res.shortfall}" if res.shortfall else ""
                print(book, res.found, f"(expected {res.expected})", warn, flush=True)
            if failed:
                print("failed books:", failed)
                raise SystemExit(1)
        else:
            fetcher = (fetch.FirecrawlFetcher(fetch.read_api_key(), client)
                       if args.fetcher == "firecrawl" else local)
            fetch.run_fetch(queue, fetcher, args.kind, book=args.book, limit=args.limit,
                            include_passages=args.include_passages)
            print(queue.counts_by(args.kind, args.book))


if __name__ == "__main__":
    main()
