"""Keyless trend/SEO signals the desks do not use yet. usage: python3 trends_test.py <pageviews|gdelt|ytsuggest|mostread>"""
import gzip
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "scout-research/1.0 (aksha.shivam18@gmail.com)"}


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


SKIP = re.compile(r"^(Main_Page|Special:|Wikipedia:|Portal:|File:|Help:|Talk:|User:|Template:|Category:|-|"
                  r"मुखपृष्ठ|विशेष:)")


def pageviews():
    now = datetime.now(timezone.utc)
    for back in range(1, 6):
        h = now - timedelta(hours=back)
        url = (f"https://dumps.wikimedia.org/other/pageviews/{h:%Y}/{h:%Y-%m}/pageviews-{h:%Y%m%d-%H}0000.gz")
        t = time.time()
        try:
            raw = get(url, timeout=120)
        except Exception as e:
            print("not yet:", url, e)
            continue
        dl = time.time() - t
        top = {"en": [], "hi": []}
        with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split(" ")
                if len(parts) < 3 or parts[0] not in ("en", "hi"):
                    continue
                if SKIP.match(parts[1]):
                    continue
                top[parts[0]].append((int(parts[2]), parts[1]))
        print(f"hour {h:%Y-%m-%d %H}:00 UTC, lag {back} h, {len(raw)/1e6:.1f} MB, download {dl:.1f} s")
        for lang in ("en", "hi"):
            print(f"  top {lang}:")
            for n, title in sorted(top[lang], reverse=True)[:15]:
                print(f"    {n:>7} {urllib.parse.unquote(title)}")
        return


def mostread():
    d = datetime.now(timezone.utc) - timedelta(days=1)
    for lang in ("en", "hi"):
        try:
            j = json.loads(get(f"https://api.wikimedia.org/feed/v1/wikipedia/{lang}/featured/{d:%Y/%m/%d}"))
            arts = (j.get("mostread") or {}).get("articles", [])
            print(f"most-read {lang} for {(j.get('mostread') or {}).get('date')}: " +
                  ", ".join(a["title"] for a in arts[:12]))
        except Exception as e:
            print("mostread", lang, e)


def gdelt():
    base = "https://api.gdeltproject.org/api/v2/doc/doc"
    queries = [("sourcelang:hindi sourcecountry:IN", "artlist"), ("sourcecountry:IN", "artlist")]
    for q, mode in queries:
        url = base + "?" + urllib.parse.urlencode({"query": q, "mode": mode, "maxrecords": 25, "format": "json",
                                                   "timespan": "3h", "sort": "datedesc"})
        t = time.time()
        try:
            j = json.loads(get(url))
            arts = j.get("articles", [])
            print(f"GDELT '{q}' {len(arts)} articles in {time.time()-t:.1f} s; newest:")
            for a in arts[:8]:
                print("   ", a.get("seendate"), a.get("domain"), "|", a.get("title", "")[:110])
        except Exception as e:
            print("GDELT error", q, e)
        time.sleep(6)
    url = base + "?" + urllib.parse.urlencode({"query": '"Air India"', "mode": "timelinevolraw", "format": "json",
                                               "timespan": "2d"})
    try:
        j = json.loads(get(url))
        series = j["timeline"][0]["data"]
        print("GDELT timeline points", len(series), "last 6:", [(p["date"], p["value"]) for p in series[-6:]])
    except Exception as e:
        print("GDELT timeline error", e)


def ytsuggest():
    seeds = sys.argv[2:] or ["RJ Mitte", "आरजे मिटे", "Air India crash", "एयर इंडिया हादसा", "earthquake today",
                             "भूकंप", "Bihar election", "बिहार चुनाव"]
    for q in seeds:
        url = ("https://suggestqueries-clients6.youtube.com/complete/search?" +
               urllib.parse.urlencode({"client": "youtube", "ds": "yt", "q": q, "hl": "hi", "gl": "IN"}))
        try:
            txt = get(url, timeout=20).decode("utf-8", "replace")
            m = re.search(r"\((.*)\)\s*$", txt, re.S)
            data = json.loads(m.group(1)) if m else json.loads(txt)
            sugg = [s[0] for s in data[1]]
            print(f"{q!r}: {len(sugg)} -> {sugg[:8]}")
        except Exception as e:
            print(q, "error", e)
        time.sleep(1)


if __name__ == "__main__":
    {"pageviews": pageviews, "gdelt": gdelt, "ytsuggest": ytsuggest, "mostread": mostread}[sys.argv[1]]()
