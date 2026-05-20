"""Print full retrieved + answer for 3 'hallucination' verdicts to spot-check fairness."""
import json
import sys
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
data = json.loads((ROOT / "eval_results" / "_faithfulness_verdicts_v2.json").read_text(encoding="utf-8"))

# Pick a few hallucinations across qid: 1 (long), 10 (intro), 14 (technical), 17 (token-stringo)
for qid in [1, 10, 14, 17, 19]:
    r = next(x for x in data if x["qid"] == qid)
    v = r.get("verdict_v2", {})
    print("=" * 80)
    print(f"Q#{qid}  category={v.get('category')}  top_L2={r['rag_top_L2']:.3f}")
    print(f"Q: {r['question']}")
    print(f"\nRETRIEVED (top-{len(r['rag_top_sources'])}):")
    print(r["rag_full_text"][:1200])
    print(f"\nANSWER:")
    print(r["fresh_answer"])
    print(f"\nJUDGE unsupported_kernels:")
    for k in v.get("unsupported_kernels", []):
        print(f"  - {k}")
    print()
