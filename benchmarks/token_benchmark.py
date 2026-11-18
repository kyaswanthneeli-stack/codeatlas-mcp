"""Measure real tokenizer counts for CodeAtlas graph responses on a local Python repository.

This is a payload-size comparison, NOT equal-task accuracy, agent token savings,
context quality, model cost, or a 50k-line performance claim.
"""
import argparse
import json
import platform
import statistics
import time
from pathlib import Path

from codeatlas.index import Index


def measure(root: Path, max_symbols: int = 30, encoding_name: str = "cl100k_base"):
    try:
        import tiktoken
    except ImportError as exc:
        raise SystemExit("Install optional benchmark dependency: pip install 'tiktoken>=0.7,<1'") from exc
    root = root.resolve(strict=True)
    enc = tiktoken.get_encoding(encoding_name)
    database = root / ".codeatlas-benchmark.sqlite3"
    db = Index(root, database=database)
    try:
        t0 = time.perf_counter()
        build = db.build()
        index_ms = round(1000 * (time.perf_counter() - t0), 3)
        # Only symbols with calls. Sorted, deterministic selection; no cherry-picking.
        rows = db.db.execute(
            "SELECT DISTINCT s.id, s.path FROM symbols s "
            "JOIN calls c ON c.caller=s.id ORDER BY s.id LIMIT ?",
            (max_symbols,),
        ).fetchall()
        samples = []
        for row in rows:
            source = (root / row["path"]).read_text(encoding="utf-8")
            graph = db.get_call_graph(row["id"], depth=2)
            graph_text = json.dumps(graph, separators=(",", ":"), sort_keys=True)
            a = len(enc.encode(source))
            b = len(enc.encode(graph_text))
            samples.append({
                "symbol": row["id"],
                "source_path": row["path"],
                "full_file_tokens": a,
                "graph_json_tokens": b,
                "payload_delta_tokens": a - b,
                "ratio_graph_over_source": round(b/a, 5) if a else None,
                "resolved_graph_edges": sum(bool(e["callee"]) for e in graph["edges"]),
                "unresolved_graph_edges": sum(not bool(e["callee"]) for e in graph["edges"]),
            })
        return {
            "repository": str(root),
            "python": platform.python_version(),
            "tokenizer": f"tiktoken/{encoding_name}",
            "selection": f"first {max_symbols} symbols with call sites, ordered by symbol ID",
            "scanned_files": build["files"],
            "indexed_symbols": build["symbols"],
            "index_ms": index_ms,
            "samples": samples,
            "summary": {
                "count": len(samples),
                "sum_full_file_tokens": sum(s["full_file_tokens"] for s in samples),
                "sum_graph_json_tokens": sum(s["graph_json_tokens"] for s in samples),
                "median_full_file_tokens": statistics.median([s["full_file_tokens"] for s in samples]) if samples else None,
                "median_graph_json_tokens": statistics.median([s["graph_json_tokens"] for s in samples]) if samples else None,
            },
            "limitations": [
                "Full source file and graph JSON are NOT semantically equivalent.",
                "Repeated symbols in the same file count its source more than once.",
                "No coding agent, model quality, cost, end-to-end latency or token spend measured.",
                "Results depend on repository and tokenizer version; no generalized savings claim.",
            ],
        }
    finally:
        db.close()
        database.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-symbols", type=int, default=30)
    parser.add_argument("--encoding", default="cl100k_base")
    args = parser.parse_args()
    if not 1 <= args.max_symbols <= 100:
        parser.error("--max-symbols must be between 1 and 100")
    result = measure(args.root, args.max_symbols, args.encoding)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
