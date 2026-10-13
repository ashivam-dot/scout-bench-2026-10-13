"""Writer-LLM bake-off on a 4-vCPU GitHub runner, mirroring Orbitwire/Kyun Hua's writer (llama.cpp server,
JSON-schema output, thinking off, name/number gate, a fact-check pass).

usage: python bench_llm.py <variant>   -> out/<variant>.json
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tarfile
import time
import urllib.parse
from pathlib import Path

import requests

RELEASE = "b11517"
UA = "scout-bench/1.0 (https://github.com/ashivam-dot; research)"
CACHE = Path("cache")
OUT = Path("out")

VARIANTS = {
    "gemma-4-12b": {"model": ("google/gemma-4-12B-it-qat-q4_0-gguf", "gemma-4-12b-it-qat-q4_0.gguf")},
    "gemma-4-12b-spec-e2b": {"model": ("google/gemma-4-12B-it-qat-q4_0-gguf", "gemma-4-12b-it-qat-q4_0.gguf"),
                             "draft": ("google/gemma-4-E2B-it-qat-q4_0-gguf", "gemma-4-E2B_q4_0-it.gguf")},
    "gemma-4-e4b": {"model": ("google/gemma-4-E4B-it-qat-q4_0-gguf", "gemma-4-E4B_q4_0-it.gguf")},
    "qwen3.5-9b": {"model": ("unsloth/Qwen3.5-9B-GGUF", "Qwen3.5-9B-Q4_K_M.gguf")},
    "qwen3.5-35b-a3b": {"model": ("unsloth/Qwen3.5-35B-A3B-GGUF", "Qwen3.5-35B-A3B-UD-IQ3_XXS.gguf")},
}

SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string"},
    "beats": {"type": "array", "minItems": 6, "maxItems": 9, "items": {"type": "object", "properties": {
        "say": {"type": "string"}, "photo": {"type": "integer"}, "caption": {"type": "string"}},
        "required": ["say", "photo", "caption"]}}},
    "required": ["title", "beats"]}
HI_SCHEMA = json.loads(json.dumps(SCHEMA))
HI_SCHEMA["properties"]["names"] = {"type": "array", "items": {"type": "object", "properties": {
    "hi": {"type": "string"}, "en": {"type": "string"}}, "required": ["hi", "en"]}}
HI_SCHEMA["required"].append("names")
CHECK_SCHEMA = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "object", "properties": {
    "line": {"type": "integer"}, "quote": {"type": "string"},
    "verdict": {"type": "string", "enum": ["supported", "partly", "unsupported"]}, "why": {"type": "string"}},
    "required": ["line", "quote", "verdict", "why"]}}}, "required": ["lines"]}

SYSTEM = ("You are the head writer of Orbitwire, a YouTube Shorts channel that tells the world's biggest stories with "
          "warmth, dignity and complete accuracy. Your narration sounds like a great documentary narrator speaking to "
          "one person: vivid, human and emotional, never robotic and never a list of facts. You never invent anything.")
HI_SYSTEM = ("You are the head writer of a Hindi YouTube Shorts news channel for Indian viewers. You tell the biggest "
             "stories in India and the world in natural, spoken Hindi written in Devanagari, the way a respected Hindi "
             "news anchor tells a story to one listener: warm, clear and human, with feeling that fits the story, "
             "never sensational. Terms Hindi news keeps in English (flight numbers, agency names such as NDRF or NASA) "
             "may stay in Latin letters. You never invent anything.")
DEATH_BRIEF = """STORY: {name} has died. Write a tribute Short that makes a viewer who barely knew {name} feel the loss,
and makes a fan feel {pronoun} was honoured.

Shape:
1. Hook (beat 1, under 15 words): say plainly that {name} has died, with the one detail that makes it matter.
2. Where {pronoun} began, or the struggle before success.
3. The turning point or breakthrough, naming the specific work from the SOURCE.
4. The work people loved most, and what made {object} different from everyone else.
5. A human detail from the SOURCE that shows who {pronoun} was off screen or off stage.
6. Legacy: what {pronoun} leaves behind. The last beat is one short, moving sentence.
Do not describe the cause or manner of death unless the SOURCE states it plainly; never mention suicide."""
INCIDENT_BRIEF = """STORY: {name}. Write a news Short that helps a viewer understand what happened and why the world is
watching, with compassion for everyone affected.

Shape:
1. Hook (beat 1, under 15 words): what happened and where, stated plainly, with the detail that makes it matter.
2. The moment it began, in order, as a story.
3. The people involved and what they faced, with official figures only if the SOURCE gives them.
4. The response: rescuers, officials, investigators.
5. What is still unknown or under investigation, said honestly.
6. Why it matters now. The last beat is one short, steady sentence.
Never name or describe any attacker, perpetrator or suspect. Never guess at causes. No graphic detail of injuries or
death."""
HI_INCIDENT_BRIEF = INCIDENT_BRIEF.replace("Write a news Short", "Write a Hindi news Short").replace(
    "under 15 words", "under 14 words")
RULES = """RULES (all mandatory):
- Use ONLY information in CONFIRMED FACTS and SOURCE. Never add a name, title, number, place, date, quote, award or
  relationship that is not written there. If you are unsure, leave it out.
- 7 or 8 beats and 110 to 130 words in total (about 45 seconds spoken). Each beat is one or two spoken sentences
  of 12 to 20 words. Count the words before you answer.
- Every beat must carry a specific fact from the SOURCE (a work, a place, a year, an honour, a choice they made);
  feeling comes from how you tell those facts, not from vague praise.
- Tell it as a story, not a list: vary how beats open, and never start more than 2 beats with the same word
  ("She", "He", "The"). Open beats with the moment, the work, the year or the turn ("In 1954, ...", "Then came ...").
- Write numbers as digits (1994, 75). Use a year only when it helps the story.
- Respectful, warm English. No slang, no hype ("shocking", "insane", "legendary", "breaking"), no "RIP", no emojis,
  no questions to the viewer, no request to like or follow.
- photo: the index of the PHOTO that best fits the beat. Beat 1 uses photo 0. Use every photo at least once if
  you can, and the same photo at most twice.
- caption: 1 to 4 words shown on screen that match what the beat says: the exact work title it names with its year,
  a role, an honour, or a year. Never a place name: viewers read a place over a photo as where the photo was taken.
- title: 30 to 60 characters in normal title case, factual and moving, includes "{name}", no clickbait.
Return only the JSON."""
HI_RULES = """RULES (all mandatory):
- Use ONLY information in CONFIRMED FACTS and the SOURCES. Never add a name, title, number, place, date, quote, award
  or relationship that is not written there. If you are unsure, leave it out.
- Write in Hindi (Devanagari): simple, spoken Hindi of a good Hindi news bulletin, neither heavily Sanskritised nor
  slang. 7 or 8 beats and 95 to 120 Hindi words in total (about 45 seconds spoken). Each beat is one or two spoken
  sentences of 10 to 18 words. Count the words before you answer.
- Every beat must carry a specific fact from the SOURCES; feeling comes from how you tell those facts.
- Tell it as a story, not a list: vary how beats open, and never start more than 2 beats with the same word.
- Write every number as digits: years (1994), ages (75), dates ("10 अक्टूबर 2026"), and big numbers with लाख or
  करोड़ ("3 लाख", "1.5 करोड़"). A number must be exactly what the SOURCES say (a million is 10 लाख).
- No hype or clickbait (सनसनीखेज, चौंकाने वाला, खौफनाक, ब्रेकिंग, बड़ी खबर), no emoji, no questions to the viewer, no
  request to like, share, subscribe or follow.
- names: list EVERY proper noun you used as {{"hi": the name exactly as written in your Hindi text, "en": the same
  name exactly as the English SOURCE writes it}}.
- photo: the index of the PHOTO that best fits the beat. Beat 1 uses photo 0.
- caption: 1 to 4 Hindi words shown on screen that match what the beat says. Never a place name.
- title: Hindi, 25 to 70 characters, factual and moving, includes {name_hi}, no clickbait.
Return only the JSON."""

TASKS = [
    {"id": "death-en", "lang": "en", "title": "Robert Redford", "name": "Robert Redford", "pronoun": "he",
     "brief": DEATH_BRIEF, "facts": ["Robert Redford died on 16 September 2025.",
                                     "Robert Redford was born on 18 August 1936."],
     "photos": ["Robert Redford at the Sundance Film Festival", "Robert Redford in a 1970s film still",
                "Robert Redford receiving an award", "Robert Redford portrait"]},
    {"id": "incident-en", "lang": "en", "title": "Air India Flight 171", "name": "Air India Flight 171",
     "brief": INCIDENT_BRIEF, "facts": ["Air India Flight 171 crashed on 12 June 2025 in Ahmedabad, India."],
     "photos": ["A Boeing 787-8 Dreamliner of Air India", "Ahmedabad airport", "Rescue workers at the crash site",
                "Memorial candles"]},
    {"id": "incident-hi", "lang": "hi", "title": "Air India Flight 171", "name": "Air India Flight 171",
     "name_hi": "एयर इंडिया फ़्लाइट 171", "brief": HI_INCIDENT_BRIEF,
     "facts": ["Air India Flight 171 crashed on 12 June 2025 in Ahmedabad, India."],
     "photos": ["A Boeing 787-8 Dreamliner of Air India", "Ahmedabad airport", "Rescue workers at the crash site",
                "Memorial candles"]},
]
COMMON = set("""a an and as at after before but by even every for from he her his how in it its now on one only
or she so still that the their then there these they this those through today tonight until what when where which while
who whose with without yet years decades across beyond never always more most many few once later soon over under
into first last no not our we you your all both each some such here once again ever forever""".split())


def download(url: str, path: Path) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    with requests.get(url, stream=True, timeout=60, headers={"User-Agent": UA}) as r:
        r.raise_for_status()
        with part.open("wb") as fh:
            for chunk in r.iter_content(1 << 22):
                fh.write(chunk)
    part.rename(path)
    return path


def server_binary() -> Path:
    tgz = download(f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/llama-{RELEASE}-bin-ubuntu-x64.tar.gz",
                   CACHE / f"llama-{RELEASE}.tar.gz")
    with tarfile.open(tgz) as t:
        t.extractall(CACHE, filter="data")
    exe = next(CACHE.rglob("llama-server"))
    exe.chmod(0o755)
    return exe


def hf_file(repo: str, file: str) -> Path:
    return download(f"https://huggingface.co/{repo}/resolve/main/{file}", CACHE / file)


def wiki_text(title: str, lang: str = "en", cap: int = 7000) -> str:
    r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", params={
        "action": "query", "prop": "extracts", "explaintext": 1, "titles": title, "format": "json", "redirects": 1},
        headers={"User-Agent": UA}, timeout=30)
    page = next(iter(r.json()["query"]["pages"].values()))
    text = page.get("extract", "")
    text = re.split(r"\n== (See also|References|Notes|External links) ==", text)[0]
    return text[:cap]


def hi_title(title: str) -> str | None:
    r = requests.get("https://en.wikipedia.org/w/api.php", params={
        "action": "query", "prop": "langlinks", "lllang": "hi", "titles": title, "format": "json", "redirects": 1},
        headers={"User-Agent": UA}, timeout=30)
    page = next(iter(r.json()["query"]["pages"].values()))
    links = page.get("langlinks") or []
    return links[0]["*"] if links else None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def english_lexicon() -> set[str]:
    try:
        import importlib.resources as res
        words = json.loads((res.files("misaki") / "data" / "us_gold.json").read_text(encoding="utf-8"))
        return {w for w in words if w.islower()} | COMMON
    except Exception:
        return COMMON


LEX: set[str] = set()


def numbers(text: str) -> list[str]:
    return [n.replace(",", "") for n in re.findall(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?", text)]


def ungrounded(text: str, source: str) -> list[str]:
    low = source.lower()
    src = set(numbers(source))
    problems = [n for n in numbers(text) if n not in src]
    for m in re.finditer(r"\b[A-Z][\w'’\-]*", text):
        word = m.group(0).strip("'’-")
        key = re.sub(r"['’]s$", "", word).lower()
        if len(key) < 2 or key in LEX or re.search(r"\b" + re.escape(key) + r"\b", low):
            continue
        problems.append(word)
    return sorted(set(problems))


def validate(task: dict, draft: dict, ground: str) -> list[str]:
    problems = []
    beats = draft.get("beats", [])
    if task["lang"] == "en":
        words = sum(len(b["say"].split()) for b in beats)
        if not 85 <= words <= 145:
            problems.append(f"the script has {words} words; it must have 100 to 130")
        if not beats or task["name"].split()[-1].lower() not in beats[0]["say"].lower():
            problems.append(f"beat 1 must name {task['name']}")
        text = " ".join(b["say"] + " " + b["caption"] for b in beats) + " " + draft.get("title", "")
        bad = ungrounded(text, ground)
        if bad:
            problems.append("these names or numbers are not in the sources: " + ", ".join(bad))
    else:
        text = " ".join(b["say"] for b in beats)
        words = len(text.split())
        if not 80 <= words <= 135:
            problems.append(f"the script has {words} Hindi words; it must have 95 to 120")
        letters = [c for c in text if c.isalpha()]
        dev = sum(1 for c in letters if "\u0900" <= c <= "\u097f") / max(1, len(letters))
        if dev < 0.85:
            problems.append(f"only {dev:.0%} of letters are Devanagari")
        src = set(numbers(ground))
        bad = [n for n in numbers(text + " " + draft.get("title", "")) if n not in src]
        if bad:
            problems.append("these numbers are not in the sources: " + ", ".join(sorted(set(bad))))
        for p in draft.get("names", []):
            en = p.get("en", "")
            for tok in re.findall(r"[A-Za-z]{3,}", en):
                if tok.lower() not in ground.lower() and tok.lower() not in LEX:
                    problems.append(f"name not in sources: {en}")
                    break
    for b in beats:
        if not 0 <= b.get("photo", -1) < len(task["photos"]):
            problems.append(f"photo {b.get('photo')} does not exist")
    openers = [re.sub(r"\W", "", b["say"].split()[0]).lower() for b in beats if b["say"].split()]
    problems += [f"{openers.count(w)} beats start with \"{w}\"" for w in sorted(set(openers)) if openers.count(w) > 2]
    return problems


class Server:
    def __init__(self, variant: dict, ctx: int = 12288):
        self.variant, self.ctx, self.port, self.proc = variant, ctx, free_port(), None

    def __enter__(self):
        exe = server_binary()
        model = hf_file(*self.variant["model"])
        cmd = [str(exe), "-m", str(model), "--port", str(self.port), "--host", "127.0.0.1", "-c", str(self.ctx),
               "-t", str(os.cpu_count() or 4), "--jinja", "--no-webui"]
        if "draft" in self.variant:
            cmd += ["-md", str(hf_file(*self.variant["draft"])), "--draft-max", "8", "--draft-min", "1"]
        env = dict(os.environ, LD_LIBRARY_PATH=str(exe.parent))
        t = time.monotonic()
        self.log = open(OUT / "server.log", "w")
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT, env=env)
        while time.monotonic() - t < 900:
            if self.proc.poll() is not None:
                raise RuntimeError("llama-server exited; see server.log")
            try:
                if requests.get(f"http://127.0.0.1:{self.port}/health", timeout=2).status_code == 200:
                    self.load_s = round(time.monotonic() - t, 1)
                    return self
            except requests.RequestException:
                pass
            time.sleep(1)
        raise RuntimeError("not ready")

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(30)

    def chat(self, messages, schema, temperature, max_tokens):
        body = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens, "top_p": 0.95,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_schema", "json_schema": {"name": "out", "schema": schema,
                                                                           "strict": True}}}
        t = time.monotonic()
        r = requests.post(f"http://127.0.0.1:{self.port}/v1/chat/completions", json=body, timeout=2400)
        r.raise_for_status()
        j = r.json()
        tim = j.get("timings", {})
        stat = {"wall_s": round(time.monotonic() - t, 1), "prompt_n": tim.get("prompt_n"),
                "prompt_tps": round(tim.get("prompt_per_second") or 0, 1), "gen_n": tim.get("predicted_n"),
                "gen_tps": round(tim.get("predicted_per_second") or 0, 2),
                "draft_n": tim.get("draft_n"), "draft_accepted": tim.get("draft_n_accepted")}
        text = j["choices"][0]["message"]["content"]
        try:
            return json.loads(text), stat
        except json.JSONDecodeError:
            return {"_raw": text}, stat


def main(name: str) -> None:
    global LEX
    LEX = english_lexicon()
    OUT.mkdir(exist_ok=True)
    variant = VARIANTS[name]
    result = {"variant": name, "release": RELEASE, "cpus": os.cpu_count(), "tasks": []}
    sources = {}
    for task in TASKS:
        key = (task["title"], task["lang"])
        if key not in sources:
            en = wiki_text(task["title"])
            hi = ""
            if task["lang"] == "hi":
                ht = hi_title(task["title"])
                hi = wiki_text(ht, "hi", 3000) if ht else ""
            sources[key] = (en, hi)
    t0 = time.monotonic()
    with Server(variant) as srv:
        result["load_s"] = srv.load_s
        for task in TASKS:
            en, hi = sources[(task["title"], task["lang"])]
            listing = "\n".join(f"{i}: {p}" for i, p in enumerate(task["photos"]))
            facts = "\n".join(f"- {f}" for f in task["facts"])
            if task["lang"] == "en":
                brief = task["brief"].format(name=task["name"], pronoun=task.get("pronoun", "it"),
                                             object={"he": "him", "she": "her"}.get(task.get("pronoun"), "it"))
                user = (brief + "\n\nCONFIRMED FACTS:\n" + facts + "\n\nSOURCE (Wikipedia):\n" + en + "\n\nPHOTOS:\n"
                        + listing + "\n\n" + RULES.format(name=task["name"]))
                msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
                schema, max_tokens = SCHEMA, 1200
            else:
                brief = task["brief"].format(name=task["name_hi"])
                user = (brief + "\n\nCONFIRMED FACTS:\n" + facts + "\n\nSOURCE (English Wikipedia):\n" + en
                        + ("\n\nSOURCE (Hindi Wikipedia):\n" + hi if hi else "") + "\n\nPHOTOS:\n" + listing
                        + "\n\n" + HI_RULES.format(name_hi=task["name_hi"]))
                msgs = [{"role": "system", "content": HI_SYSTEM}, {"role": "user", "content": user}]
                schema, max_tokens = HI_SCHEMA, 2400
            ground = en + "\n" + hi + "\n" + facts + "\n" + listing
            rec = {"id": task["id"], "attempts": []}
            tt = time.monotonic()
            for attempt in range(3):
                draft, stat = srv.chat(msgs, schema, 0.75 if attempt == 0 else 0.6, max_tokens)
                problems = ["unparseable JSON"] if "_raw" in draft else validate(task, draft, ground)
                rec["attempts"].append({"draft": draft, "problems": problems, "stat": stat})
                print(name, task["id"], "attempt", attempt + 1, stat, problems[:3], flush=True)
                if not problems:
                    break
                msgs = msgs + [{"role": "assistant", "content": json.dumps(draft, ensure_ascii=False)},
                               {"role": "user", "content": "Rewrite the whole JSON. Fix these problems and change "
                                "nothing else that is supported:\n- " + "\n- ".join(problems)}]
            last = rec["attempts"][-1]
            rec["passed_gate"] = not last["problems"]
            if task["lang"] == "en" and "_raw" not in last["draft"]:
                lines = [b["say"] for b in last["draft"].get("beats", [])]
                cu = ("Check every numbered LINE of a news script against CONFIRMED FACTS and SOURCE. For each line, "
                      "copy word for word the sentence from SOURCE or CONFIRMED FACTS that supports it (\"quote\"), "
                      "then give a verdict: supported, partly or unsupported. In \"why\", name the exact detail no "
                      "source states.\n\nCONFIRMED FACTS:\n" + facts + "\n\nSOURCE:\n" + en + "\n\nLINES:\n"
                      + "\n".join(f"{i}. {l}" for i, l in enumerate(lines, 1)))
                verdict, stat = srv.chat([{"role": "system", "content": "You are a meticulous fact-checker for a news "
                                           "channel."}, {"role": "user", "content": cu}], CHECK_SCHEMA, 0.0, 1800)
                rec["check"] = {"verdict": verdict, "stat": stat}
                print(name, task["id"], "check", stat, flush=True)
            rec["task_s"] = round(time.monotonic() - tt, 1)
            result["tasks"].append(rec)
            (OUT / f"{name}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    result["total_s"] = round(time.monotonic() - t0, 1)
    (OUT / f"{name}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
