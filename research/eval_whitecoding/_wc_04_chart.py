"""L2 distribution chart: relevant vs distractor pairs for the White Coding RAG."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
m = json.loads((HERE / "_retrieval_metrics.json").read_text(encoding="utf-8"))

# Re-derive L2 lists from per_query is not stored; recompute is overkill —
# instead read the saved means and rebuild histograms from the metrics run.
# We re-run a light retrieval to get the raw L2 values.
import os
REPO = Path(__file__).resolve().parents[2]
os.chdir(REPO)
os.environ["KMP_DUPLICATE_LIB_OK"] = "True"
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
sys.path.insert(0, str(REPO / "src"))
from langchain_community.vectorstores import FAISS  # noqa
from agent.llm_clients.lc_clients import get_embeddings_model  # noqa

emb = get_embeddings_model()
vec = FAISS.load_local(str(REPO / "data" / "rag_vector_store"), emb,
                       index_name="knowledge", allow_dangerous_deserialization=True)
chunks = json.loads((HERE / "_chunks.json").read_text(encoding="utf-8"))
id_to_content = {c["chunk_id"]: c["content"] for c in chunks}
gt = json.loads((HERE / "_gt_questions.json").read_text(encoding="utf-8"))

rel, dis = [], []
for q in gt:
    gt_content = id_to_content[q["gt_chunk_id"]]
    ds = vec.similarity_search_with_score(q["question"], k=len(id_to_content))
    for i, (d, s) in enumerate(ds):
        if d.page_content == gt_content:
            rel.append(float(s))
            break
    for d, s in ds[:10]:
        if d.page_content != gt_content:
            dis.append(float(s))

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.figure(figsize=(8, 4.5))
    edges = [i * 0.1 for i in range(16)]
    plt.hist(rel, bins=edges, alpha=0.75, color="#2c7a3a",
             label=f"релевантные (вопрос<->нужный кусок), n={len(rel)}")
    plt.hist(dis, bins=edges, alpha=0.5, color="#a63a3a",
             label=f"дистракторы (вопрос<->чужой кусок), n={len(dis)}")
    plt.axvline(m["best_f1_threshold"], color="blue", linestyle="--", linewidth=1.5,
                label=f"порог F1-opt = {m['best_f1_threshold']:.2f}")
    plt.xlabel("L2-расстояние (меньше = ближе по смыслу)")
    plt.ylabel("количество пар")
    plt.title("RAG «Вайб-кодинг»: разделимость релевантных и нерелевантных кусков")
    plt.legend(fontsize=8)
    plt.tight_layout()
    out = HERE / "L2_distribution_whitecoding.png"
    plt.savefig(out, dpi=130)
    print(f"saved -> {out}")
except Exception as e:
    print(f"matplotlib skipped: {e}")
