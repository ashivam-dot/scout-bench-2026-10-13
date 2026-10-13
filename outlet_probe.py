"""Which trusted outlets' RSS feeds and article pages are readable without a key, and how much article text comes out."""
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import trafilatura

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
FEEDS = {
    "PIB (Govt of India)": "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
    "PIB Hindi": "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=2&Regid=3",
    "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "BBC India": "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml",
    "BBC Hindi": "https://feeds.bbci.co.uk/hindi/rss.xml",
    "DW English": "https://rss.dw.com/rdf/rss-en-all",
    "DW Hindi": "https://rss.dw.com/rdf/rss-hi-all",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "Guardian World": "https://www.theguardian.com/world/rss",
    "NPR World": "https://feeds.npr.org/1004/rss.xml",
    "France 24": "https://www.france24.com/en/rss",
    "UN News": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
    "UN News Hindi": "https://news.un.org/feed/subscribe/hi/news/all/rss.xml",
    "ReliefWeb (UN OCHA)": "https://reliefweb.int/updates/rss.xml",
    "The Hindu National": "https://www.thehindu.com/news/national/feeder/default.rss",
    "Indian Express India": "https://indianexpress.com/section/india/feed/",
    "Hindustan Times India": "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
    "NDTV Top": "https://feeds.feedburner.com/ndtvnews-top-stories",
    "Times of India Top": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "Deccan Herald National": "https://www.deccanherald.com/india/rssfeed.xml",
    "Live Hindustan (Hindi)": "https://api.livehindustan.com/feeds/rss/national/rssfeed.xml",
    "Amar Ujala (Hindi)": "https://www.amarujala.com/rss/breaking-news.xml",
    "Dainik Jagran (Hindi)": "https://www.jagran.com/rss/news/national.xml",
    "NDTV India (Hindi)": "https://feeds.feedburner.com/ndtvkhabar-latest",
    "AajTak (Hindi)": "https://www.aajtak.in/rssfeeds/?id=home",
    "ABP Live Hindi": "https://www.abplive.com/home/feed",
    "Google News search": "https://news.google.com/rss/search?q=India+when:1d&hl=en-IN&gl=IN&ceid=IN:en",
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def probe(item):
    name, url = item
    row = {"outlet": name, "feed": "fail", "items": 0, "text_chars": 0, "note": ""}
    try:
        root = ET.fromstring(get(url))
        items = [i for i in root.iter() if i.tag.split("}")[-1] == "item"]
        row["items"] = len(items)
        row["feed"] = "ok" if items else "empty"
        link = None
        for i in items[:3]:
            for ch in i:
                if ch.tag.split("}")[-1] == "link":
                    link = (ch.text or ch.get("href") or "").strip()
            if link and "google.com" not in name.lower():
                try:
                    text = trafilatura.extract(get(link).decode("utf-8", "replace")) or ""
                    row["text_chars"] = max(row["text_chars"], len(text))
                    if row["text_chars"] > 800:
                        break
                except Exception as exc:
                    row["note"] = f"article: {type(exc).__name__} {str(exc)[:60]}"
    except Exception as exc:
        row["note"] = f"feed: {type(exc).__name__} {str(exc)[:60]}"
    return row


with ThreadPoolExecutor(8) as pool:
    rows = list(pool.map(probe, FEEDS.items()))
for r in rows:
    print(f"{r['outlet']:<26} feed={r['feed']:<5} items={r['items']:<4} article_text={r['text_chars']:<6} {r['note']}")
if len(sys.argv) > 1:
    open(sys.argv[1], "w").write(json.dumps(rows, indent=1))
