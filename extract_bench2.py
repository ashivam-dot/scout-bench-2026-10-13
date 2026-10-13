"""For the outlets trafilatura could not read: is a full headless browser needed, or do lighter fetches work?

a) urllib with full browser headers, b) curl_cffi impersonating Chrome's TLS fingerprint,
c) Crawl4AI's rendered HTML cleaned by trafilatura (instead of its noisy markdown).
"""
import asyncio
import urllib.request

import trafilatura
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from curl_cffi import requests as cffi

from extract_bench import junk, links
from outlet_probe import FEEDS, UA

TARGETS = ["France 24", "NDTV Top", "NDTV India (Hindi)", "NPR World", "PIB (Govt of India)", "Times of India Top",
           "BBC Hindi", "UN News Hindi"]
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
           "Sec-Fetch-Site": "none", "Upgrade-Insecure-Requests": "1"}


def text_of(html):
    t = trafilatura.extract(html) or ""
    return f"{len(t):>6}/{junk(t):<4}"


def a_headers(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=25) as r:
            return text_of(r.read().decode("utf-8", "replace"))
    except Exception as exc:
        return f"{type(exc).__name__[:12]} {str(exc)[:18]}"


def b_cffi(url):
    try:
        r = cffi.get(url, impersonate="chrome", timeout=25)
        return text_of(r.text) if r.status_code == 200 else f"HTTP {r.status_code}"
    except Exception as exc:
        return f"{type(exc).__name__[:12]} {str(exc)[:18]}"


async def main():
    print(f"{'outlet':<22} {'headers':<18} {'curl_cffi':<18} {'c4a html+traf':<18} url")
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, user_agent=UA)) as crawler:
        for name in TARGETS:
            for url in links(FEEDS[name])[:3]:
                r = await crawler.arun(url=url, config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=30000))
                c = text_of(r.html) if r.success and r.html else f"fail {r.status_code}"
                print(f"{name:<22} {a_headers(url):<18} {b_cffi(url):<18} {c:<18} {url[:70]}")


asyncio.run(main())
