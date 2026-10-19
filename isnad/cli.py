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
    args = ap.parse_args(argv)

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
