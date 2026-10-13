"""Hindi TTS bake-off on a 4-vCPU GitHub runner (CPU only). Same 8 lines Kyun Hua published on 2026-10-13
(Gemini Sulafat), cloned from a public female Indian reference clip.

usage: python bench_tts.py <engine>   -> out/<engine>/lineNN.wav + out/<engine>/stats.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

LINES = json.loads(Path(os.environ.get("LINES_FILE", "lines_hi.json")).read_text(encoding="utf-8"))
REF = "ref.wav"  # 9 s trimmed from rebuilt-in-3d tts/voices/india.wav


def run(engine: str) -> None:
    out = Path("out") / engine
    out.mkdir(parents=True, exist_ok=True)
    t_load = time.time()
    rows = []
    import torch
    torch.manual_seed(7)
    if engine == "chatterbox":
        import torchaudio as ta
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        model = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
        model.prepare_conditionals(REF, exaggeration=0.5)
        load = time.time() - t_load
        for i, text in enumerate(LINES):
            t = time.time()
            wav = model.generate(text, language_id="hi", exaggeration=0.5, cfg_weight=0.45, temperature=0.8)
            ta.save(str(out / f"line{i:02d}.wav"), wav, model.sr)
            rows.append({"seconds": wav.shape[-1] / model.sr, "took": time.time() - t})
            print(engine, i, rows[-1], flush=True)
    elif engine.startswith("omnivoice"):
        from omnivoice import OmniVoice
        steps = 16 if engine.endswith("fast") else 32
        model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cpu", dtype=torch.float32,
                                          asr_device="cpu")
        prompt = model.create_voice_clone_prompt(ref_audio=REF, ref_text=None)
        extra = {"speed": float(os.environ["OMNI_SPEED"])} if os.environ.get("OMNI_SPEED") else {}
        load = time.time() - t_load
        for i, text in enumerate(LINES):
            t = time.time()
            audio = model.generate(text=text, voice_clone_prompt=prompt, num_step=steps, **extra)
            wav = np.asarray(audio[0], dtype=np.float32)
            sf.write(out / f"line{i:02d}.wav", wav, 24000)
            rows.append({"seconds": len(wav) / 24000, "took": time.time() - t})
            print(engine, i, rows[-1], flush=True)
    elif engine == "voxcpm2":
        from voxcpm import VoxCPM
        model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
        sr = model.tts_model.sample_rate
        load = time.time() - t_load
        for i, text in enumerate(LINES):
            t = time.time()
            wav = model.generate(text=text, reference_wav_path=REF, cfg_value=2.0, inference_timesteps=10)
            sf.write(out / f"line{i:02d}.wav", wav, sr)
            rows.append({"seconds": len(wav) / sr, "took": time.time() - t})
            print(engine, i, rows[-1], flush=True)
            if sum(r["took"] for r in rows) > 1800:
                print("time cap reached", flush=True)
                break
    else:
        raise SystemExit("unknown engine")
    audio_s = sum(r["seconds"] for r in rows)
    took = sum(r["took"] for r in rows)
    stats = {"engine": engine, "load_s": round(load, 1), "audio_s": round(audio_s, 1), "synth_s": round(took, 1),
             "rtf": round(took / max(audio_s, 0.01), 2), "lines": rows}
    (out / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "lines"}), flush=True)


if __name__ == "__main__":
    run(sys.argv[1])
