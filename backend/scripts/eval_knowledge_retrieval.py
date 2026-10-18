"""
Measure retrieval against the floor committed to in the spec.

    env/Scripts/python.exe scripts/eval_knowledge_retrieval.py
    env/Scripts/python.exe scripts/eval_knowledge_retrieval.py --min-score 0.62
    env/Scripts/python.exe scripts/eval_knowledge_retrieval.py --sweep

The floor (spec 01-local-rag, "Retrieval quality bar"):

  * recall >= 0.85 over the labelled questions, at most 5 passages per question;
  * >= 0.90 of the control questions retrieve nothing, so the assistant falls back
    to "I don't have that documented" instead of answering.

Exits non-zero when either is missed, so this is a gate rather than a report.

It makes one real embedding call per question and is therefore NOT part of the
pytest suite — that suite never reaches Google.

Evaluation set — app/knowledge/eval/questions.yaml:

    questions:
      - q: does searching use up my credits?
        documents: [How lead credits work]     # titles that answer it
      - q: how do I connect my own mailbox?
        documents: [Connecting a mailbox, Sending limits]
    controls:
      - q: can I export leads straight to Salesforce?    # plausible, not documented
      - q: what is your uptime SLA?

`documents` are matched against document titles in the corpus frontmatter. A
question counts as recalled when at least one of its labelled documents appears in
the passages retrieved for it.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.knowledge.embeddings import embed_query  # noqa: E402
from app.knowledge.index import get_index  # noqa: E402

EVAL_PATH = Path(__file__).resolve().parents[1] / "app" / "knowledge" / "eval" / "questions.yaml"

RECALL_FLOOR = 0.85
CONTROL_FLOOR = 0.90

settings = get_settings()


def load_eval_set() -> tuple[list[dict], list[dict]]:
    if not EVAL_PATH.is_file():
        print(
            f"No evaluation set at {EVAL_PATH}.\n\n"
            "The floor cannot be measured without one. It needs real product and help\n"
            "questions — from chat transcripts and from what support is actually asked —\n"
            "each labelled by a person with the corpus document that answers it.\n"
            "See this script's docstring for the file format.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    payload = yaml.safe_load(EVAL_PATH.read_text(encoding="utf-8")) or {}
    return payload.get("questions") or [], payload.get("controls") or []


async def _score_all(items: list[dict], min_score: float, k: int):
    """Return (per-item retrieved titles, per-item elapsed ms)."""
    index = get_index()
    titles: list[list[str]] = []
    timings: list[float] = []
    for item in items:
        started = time.perf_counter()
        vector = await embed_query(item["q"])
        chunks = index.search(
            vector,
            k=k,
            threshold=min_score,
            stale_after_days=settings.KNOWLEDGE_STALE_AFTER_DAYS,
        )
        timings.append((time.perf_counter() - started) * 1000)
        seen: list[str] = []
        for c in chunks:
            if c.document_title not in seen:
                seen.append(c.document_title)
        titles.append(seen)
    return titles, timings


async def evaluate(min_score: float, k: int, verbose: bool) -> dict:
    labelled, controls = load_eval_set()

    index = get_index()
    if not index.available:
        print(f"Index unavailable: {index.unavailable_reason}", file=sys.stderr)
        raise SystemExit(2)

    hit_titles, hit_times = await _score_all(labelled, min_score, k)
    ctrl_titles, ctrl_times = await _score_all(controls, min_score, k)

    hits = 0
    for item, retrieved in zip(labelled, hit_titles):
        expected = {str(d).strip() for d in (item.get("documents") or [])}
        ok = bool(expected & set(retrieved))
        hits += ok
        if verbose and not ok:
            print(f"  MISS  {item['q']!r}")
            print(f"        expected one of {sorted(expected)}, got {retrieved}")

    fallbacks = 0
    for item, retrieved in zip(controls, ctrl_titles):
        ok = not retrieved
        fallbacks += ok
        if verbose and not ok:
            print(f"  LEAK  control {item['q']!r} retrieved {retrieved}")

    timings = hit_times + ctrl_times
    return {
        "min_score": min_score,
        "recall": hits / len(labelled) if labelled else 0.0,
        "labelled": len(labelled),
        "control_fallback": fallbacks / len(controls) if controls else 0.0,
        "controls": len(controls),
        "p50_ms": statistics.median(timings) if timings else 0.0,
        "p95_ms": (
            statistics.quantiles(timings, n=20)[-1] if len(timings) > 1 else (timings or [0])[0]
        ),
    }


def report(r: dict) -> bool:
    recall_ok = r["recall"] >= RECALL_FLOOR
    control_ok = r["control_fallback"] >= CONTROL_FLOOR
    print()
    print(f"min_score          {r['min_score']:.3f}")
    print(
        f"recall             {r['recall']:.3f}  over {r['labelled']} questions  "
        f"(floor {RECALL_FLOOR:.2f})  {'PASS' if recall_ok else 'FAIL'}"
    )
    print(
        f"control fallback   {r['control_fallback']:.3f}  over {r['controls']} controls  "
        f"(floor {CONTROL_FLOOR:.2f})  {'PASS' if control_ok else 'FAIL'}"
    )
    print(f"retrieval latency  p50 {r['p50_ms']:.0f} ms   p95 {r['p95_ms']:.0f} ms  (budget 500 ms)")
    return recall_ok and control_ok


async def sweep(k: int) -> None:
    print("min_score   recall   control   p95 ms")
    for step in range(40, 90, 2):
        min_score = step / 100
        r = await evaluate(min_score, k, verbose=False)
        print(
            f"{min_score:>9.2f} {r['recall']:>8.3f} {r['control_fallback']:>9.3f} "
            f"{r['p95_ms']:>8.0f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure retrieval against the floor.")
    parser.add_argument("--min-score", type=float, default=settings.KNOWLEDGE_MIN_SCORE)
    parser.add_argument("--k", type=int, default=settings.KNOWLEDGE_TOP_K)
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="try a range of thresholds instead of gating on one",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="hide per-question misses")
    args = parser.parse_args()

    if args.k > 5:
        print(
            f"--k {args.k} exceeds the 5 passages the floor was set at; "
            "the result would not be comparable.",
            file=sys.stderr,
        )
        return 2

    if args.sweep:
        asyncio.run(sweep(args.k))
        return 0

    result = asyncio.run(evaluate(args.min_score, args.k, verbose=not args.quiet))
    return 0 if report(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
