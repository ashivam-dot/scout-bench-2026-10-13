"""Crawl4AI (headless Chromium) vs trafilatura (plain HTTP) on the same article links from each trusted outlet."""
import asyncio
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

import trafilatura
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from outlet_probe import FEEDS, UA, get

PER_OUTLET = 4
GOOD = 600


def links(url):
    try:
        root = ET.fromstring(get(url))
    except Exception:
        return []
    out = []
    for i in root.iter():
        if i.tag.split("}")[-1] != "item":
            continue
        for ch in i:
            if ch.tag.split("}")[-1] == "link":
                link = (ch.text or ch.get("href") or "").strip()
                if link.startswith("http"):
                    out.append(link)
        if len(out) >= PER_OUTLET:
            break
    return out


def junk(text):
    """Share of lines that look like navigation: markdown links, or very short lines."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    bad = sum(1 for l in lines if "](" in l or len(l.strip()) < 25)
    return round(bad / len(lines), 2)


def traf(url):
    t0 = time.time()
    try:
        text = trafilatura.extract(get(url).decode("utf-8", "replace")) or ""
        err = ""
    except Exception as exc:
        text, err = "", f"{type(exc).__name__} {str(exc)[:50]}"
    return {"chars": len(text), "junk": junk(text), "s": round(time.time() - t0, 1), "err": err}


async def c4a(crawler, url):
    cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=30000,
                           markdown_generator=DefaultMarkdownGenerator(content_filter=PruningContentFilter()))
    t0 = time.time()
    try:
        r = await crawler.arun(url=url, config=cfg)
        md = r.markdown
        text = (getattr(md, "fit_markdown", None) or getattr(md, "raw_markdown", None) or str(md or "")) if r.success else ""
        err = "" if r.success else f"{r.status_code} {str(r.error_message)[:50]}"
    except Exception as exc:
        text, err = "", f"{type(exc).__name__} {str(exc)[:50]}"
    return {"chars": len(text), "junk": junk(text), "s": round(time.time() - t0, 1), "err": err}


async def main():
    rows = []
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, user_agent=UA)) as crawler:
        for name, feed in FEEDS.items():
            if "google" in name.lower():
                continue
            for url in links(feed):
                rows.append({"outlet": name, "url": url, "traf": traf(url), "c4a": await c4a(crawler, url)})
    by = {}
    for r in rows:
        b = by.setdefault(r["outlet"], {"n": 0, "traf_ok": 0, "c4a_ok": 0, "traf_chars": [], "c4a_chars": [],
                                        "traf_junk": [], "c4a_junk": [], "traf_s": 0, "c4a_s": 0, "errs": set()})
        b["n"] += 1
        for k in ("traf", "c4a"):
            ok = r[k]["chars"] >= GOOD
            b[f"{k}_ok"] += ok
            if ok:
                b[f"{k}_chars"].append(r[k]["chars"])
                b[f"{k}_junk"].append(r[k]["junk"])
            b[f"{k}_s"] += r[k]["s"]
            if r[k]["err"]:
                b["errs"].add(f"{k}:{r[k]['err']}")
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0
    print(f"{'outlet':<26} n  traf_ok c4a_ok  traf_chars c4a_chars  traf_junk c4a_junk  traf_s c4a_s  errors")
    tot = {"n": 0, "traf_ok": 0, "c4a_ok": 0, "traf_s": 0, "c4a_s": 0}
    for name, b in by.items():
        print(f"{name:<26} {b['n']}  {b['traf_ok']:<7} {b['c4a_ok']:<6}  {med(b['traf_chars']):<10} {med(b['c4a_chars']):<9}  "
              f"{med(b['traf_junk']):<9} {med(b['c4a_junk']):<8}  {b['traf_s']:<6.0f} {b['c4a_s']:<5.0f}  "
              f"{'; '.join(sorted(b['errs']))[:110]}")
        for k in tot:
            tot[k] += b[k]
    print("TOTAL", tot)
    for r in rows:
        if r["c4a"]["chars"] >= GOOD > r["traf"]["chars"]:
            print("c4a-only:", r["outlet"], r["url"])
        if r["traf"]["chars"] >= GOOD > r["c4a"]["chars"]:
            print("traf-only:", r["outlet"], r["url"])
    open(sys.argv[1] if len(sys.argv) > 1 else "extract.json", "w").write(json.dumps(rows, indent=1))


asyncio.run(main())
