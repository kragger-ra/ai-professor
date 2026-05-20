"""Probe HF dataset sizes to choose a manageable public IR benchmark."""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from huggingface_hub import HfApi

api = HfApi()
for repo in ["miracl/miracl-corpus", "mteb/RuBQRetrieval", "miracl/miracl", "BeIR/fiqa"]:
    try:
        info = api.repo_info(repo, repo_type="dataset", files_metadata=True)
        files = info.siblings or []
        ru = [f for f in files if "ru" in f.rfilename.lower()]
        total = sum((f.size or 0) for f in files)
        rutot = sum((f.size or 0) for f in ru)
        print(f"=== {repo} ===  files={len(files)}  total={total/1e6:.1f}MB  "
              f"ru-files={len(ru)} ru-total={rutot/1e6:.1f}MB  gated={info.gated}")
        for f in sorted(files, key=lambda x: -(x.size or 0))[:8]:
            print(f"   {(f.size or 0)/1e6:8.2f}MB  {f.rfilename}")
    except Exception as e:
        print(f"=== {repo} === ERROR: {type(e).__name__}: {e}")
