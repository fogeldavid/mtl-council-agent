"""One-command local English refresh; download/convert model only when missing.

Run: .venv/bin/python scripts/refresh_translations.py
Install dependencies once: uv pip install --python .venv/bin/python -e '.[translation]'
Only source records are read from Postgres. Translation inference runs on CPU.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "Helsinki-NLP/opus-mt-fr-en"


def main():
    os.chdir(ROOT)
    os.environ.setdefault("HF_HOME", str(ROOT / "scratch/huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    model_dir = ROOT / "scratch/translation-fr-en"
    tokenizer_dir = ROOT / "scratch/translation-tokenizer"
    if not (model_dir / "model.bin").exists():
        from ctranslate2.converters import TransformersConverter
        print("Preparing the local French-to-English model (one-time download).", flush=True)
        TransformersConverter(MODEL).convert(str(model_dir), quantization="int8", force=True)
    if not (tokenizer_dir / "source.spm").exists():
        from transformers import MarianTokenizer
        MarianTokenizer.from_pretrained(MODEL).save_pretrained(str(tokenizer_dir))
    command = [sys.executable, str(ROOT / "scripts/translate_records.py"),
               "--model-dir", str(model_dir), "--tokenizer-dir", str(tokenizer_dir)]
    # Prioritize titles. Retry rejected numbers with protected placeholders;
    # each pass reuses saved translations and never retranslates unchanged entries.
    for options in (["--titles-only"], ["--titles-only", "--protect-numbers"],
                    [], ["--protect-numbers"]):
        subprocess.run(command + options, check=True)
    print("English refresh complete. Saved JSON is ready for the app; "
          "review exceptions remain French. See scratch/translation-review.json.", flush=True)


if __name__ == "__main__":
    main()
