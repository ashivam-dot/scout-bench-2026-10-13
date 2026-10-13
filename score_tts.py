"""Score each engine's Hindi takes: Whisper CER against the script, words per minute, UTMOS22 (English-trained,
used only as an artefact/naturalness signal), and ECAPA speaker similarity to the reference.

usage: python score_tts.py <dir with engine subfolders> -> scores.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

LINES = json.loads(Path(os.environ.get("LINES_FILE", "lines_hi.json")).read_text(encoding="utf-8"))


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[0-9०-९]+", " ", s)
    s = re.sub(r"[^\u0900-\u097F ]", " ", s)
    s = s.replace("़", "")  # nukta spelling varies
    return " ".join(s.split())


def cer(ref: str, hyp: str) -> float:
    r, h = list(norm(ref).replace(" ", "")), list(norm(hyp).replace(" ", ""))
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / max(1, len(r))


def load16(path: Path) -> torch.Tensor:
    wav, sr = sf.read(str(path), dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(1)
    t = torch.from_numpy(wav)[None]
    return torchaudio.functional.resample(t, sr, 16000) if sr != 16000 else t


def main(root: str) -> None:
    from faster_whisper import WhisperModel
    from speechbrain.inference.speaker import EncoderClassifier
    asr = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    utmos = torch.hub.load("tarepan/SpeechMOS:v1.2.0", "utmos22_strong", trust_repo=True)
    spk = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": "cpu"})
    ref_emb = spk.encode_batch(load16(Path("ref.wav"))).squeeze()
    scores = {}
    for d in sorted(Path(root).iterdir()):
        files = sorted(d.glob("line*.wav"))
        if not files:
            continue
        rows, words, secs = [], 0, 0.0
        for i, f in enumerate(files):
            wav16 = load16(f)
            segs, _ = asr.transcribe(str(f), language="hi", beam_size=5)
            hyp = " ".join(s.text for s in segs)
            c = cer(LINES[i], hyp)
            mos = float(utmos(wav16, 16000).item())
            sim = float(torch.nn.functional.cosine_similarity(spk.encode_batch(wav16).squeeze(), ref_emb, dim=0))
            dur = wav16.shape[-1] / 16000
            words += len(LINES[i].split())
            secs += dur
            rows.append({"line": i, "cer": round(c, 3), "utmos": round(mos, 2), "spk_sim": round(sim, 3),
                         "seconds": round(dur, 2), "heard": hyp})
        stats = {}
        sp = d / "stats.json"
        if sp.exists():
            stats = {k: v for k, v in json.loads(sp.read_text()).items() if k != "lines"}
        scores[d.name] = {**stats, "mean_cer": round(float(np.mean([r["cer"] for r in rows])), 3),
                          "max_cer": round(max(r["cer"] for r in rows), 3),
                          "mean_utmos": round(float(np.mean([r["utmos"] for r in rows])), 2),
                          "mean_spk_sim": round(float(np.mean([r["spk_sim"] for r in rows])), 3),
                          "wpm": round(words / max(secs, 0.1) * 60, 1), "lines": rows}
        print(d.name, {k: v for k, v in scores[d.name].items() if k != "lines"}, flush=True)
    Path("scores.json").write_text(json.dumps(scores, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
