"""CLI: python -m isnad.cli <fetch|build|gold|score|validate|report|export> ..."""

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
    r.add_argument("--batch-size", type=int, default=100)
    r.add_argument("--concurrency", type=int, default=1)
    r.add_argument("--limit", type=int)
    r.add_argument("--include-passages", action="store_true")
    r.add_argument("--no-compress", action="store_true", help="write plain .html instead of .html.gz")
    r.add_argument("--shard", help="K/N: this worker takes pending rows with rowid %% N == K")
    f.add_parser("jobs", help="list submitted Firecrawl jobs from the ledger")
    rc = f.add_parser("recover", help="persist the results of an existing Firecrawl job")
    rc.add_argument("--job", required=True)
    rc.add_argument("--kind", choices=["rawi", "hadith"], help="needed if the job is not in the ledger")
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
    gp.add_argument("--tuhfa-frame",
                    help="re-resolve this existing denials_tuhfa parquet; skips the LLM runner")
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
    ep = top.add_parser("export")
    ep.add_argument("--data-dir", default="data")
    ep.add_argument("--out", default="release")
    args = ap.parse_args(argv)

    if args.cmd == "export":
        from isnad import export
        for name, info in export.run_export(args.data_dir, args.out).items():
            print(name, info["rows"], "rows")
        return

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
        print({k: m[k] for k in ("n_positives", "n_positives_scored", "false_flag_rate")})
        for src, rels in m["negatives"].items():
            for rel, c in rels.items():
                print(src, rel, {k: c[k] for k in ("n", "auroc", "recall@0.05", "n_in_corpus",
                                                   "text_recall_in_corpus_excl_denial")})
        return

    if args.cmd == "gold":
        from isnad import gold
        gold.run_gold(args.rawi, args.tuhfa, args.marasil, args.out_dir,
                      tuhfa_frame=args.tuhfa_frame)
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
        print(score.format_term_table(score.term_table(df)))
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
    if args.sub == "jobs":
        for j in queue.jobs():
            print(j["job_id"], j["kind"], j["n"], j["status"], j["submitted_at"],
                  j["first_url"], j["last_url"])
        return
    if (args.sub == "run" and args.fetcher == "firecrawl" and args.kind == "hadith"
            and args.book is None and args.limit is None):
        n = len(queue.pending(kind="hadith", include_passages=args.include_passages))
        print(f"refusing: {n} hadith pages pending across all books; run Stage 2 per book "
              "with --book b-N (or cap the run with --limit N)")
        raise SystemExit(2)
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
                if res.failed_chapters:  # rows kept; status failed so a re-run retries the book
                    failed.append((book, f"failed chapters {res.failed_chapters}"))
                    queue.mark_book(book, "failed", res.found, res.expected)
                    print(book, "FAILED chapters", res.failed_chapters, flush=True)
                    continue
                queue.mark_book(book, "done", res.found, res.expected)
                warn = f"  WARNING shortfall {res.shortfall}" if res.shortfall else ""
                print(book, res.found, f"(expected {res.expected})", warn, flush=True)
            if failed:
                print("failed books:", failed)
                raise SystemExit(1)
        elif args.sub == "recover":
            fc = fetch.FirecrawlFetcher(fetch.read_api_key(), client)
            fetch.recover_job(queue, fc, args.job, kind=args.kind)
        else:
            fetcher = (fetch.FirecrawlFetcher(fetch.read_api_key(), client, batch_size=args.batch_size,
                                            concurrency=args.concurrency,
                                            ledger=queue.ledger(args.kind))
                       if args.fetcher == "firecrawl" else local)
            shard = None
            if args.shard:
                k, n = (int(x) for x in args.shard.split("/"))
                shard = (k, n)
            fetch.run_fetch(queue, fetcher, args.kind, book=args.book, limit=args.limit,
                            include_passages=args.include_passages, shard=shard, compress=not args.no_compress)
            print(queue.counts_by(args.kind, args.book))


if __name__ == "__main__":
    main()
