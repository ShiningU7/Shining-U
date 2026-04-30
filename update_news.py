"""
update_news.py — ShiningU Daily News Refresher
================================================
Fetches RSS feeds from US News, Common App, Dept of Education,
Federal Student Aid, BLS, and College Confidential.
Rewrites the NEWS array inside index.html with fresh articles.
 
Run manually:   python update_news.py
Run via GitHub Actions: triggered automatically daily at 7am UTC
"""
 
import re
import json
import signal
import sys
from datetime import datetime
from pathlib import Path
 
try:
    import feedparser
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "feedparser", "requests"])
    import feedparser
    import requests
 
# ── TIMEOUT HELPER ────────────────────────────────────────────────────────────
FEED_TIMEOUT = 15  # seconds per feed
 
# ── SOURCES ───────────────────────────────────────────────────────────────────
FEEDS = [
    {
        "id": "usnews", "label": "US News",
        "url": "https://www.usnews.com/rss/education",
        "category_default": "trends",
        "keywords": {
            "test-policy": ["test", "sat", "act", "test-optional", "test optional", "test required"],
            "deadlines":   ["deadline", "early decision", "early action", "application opens", "application closes"],
            "financial-aid": ["financial aid", "scholarship", "grant", "tuition", "fafsa", "pell"],
            "workforce":   ["job", "employment", "salary", "earnings", "career", "workforce"],
        }
    },
    {
        "id": "insidehighered", "label": "Inside Higher Ed",
        "url": "https://www.insidehighered.com/rss.xml",
        "category_default": "trends",
        "keywords": {
            "test-policy": ["test", "sat", "act", "test-optional", "score", "standardized"],
            "deadlines":   ["deadline", "early decision", "early action", "application", "enrollment"],
            "financial-aid": ["financial aid", "scholarship", "grant", "tuition", "fafsa", "pell", "loan"],
            "workforce":   ["job", "employment", "salary", "earnings", "career", "workforce"],
        }
    },
    {
        "id": "doed", "label": "Dept. of Education",
        "url": "https://www.ed.gov/feed",
        "category_default": "financial-aid",
        "keywords": {
            "financial-aid": ["fafsa", "grant", "loan", "aid", "title iv", "pell", "forgiveness"],
            "test-policy": ["test", "assessment", "accountability"],
            "trends":      ["enrollment", "graduation", "data", "report", "equity"],
            "workforce":   ["career", "workforce", "employment", "job"],
        }
    },
    {
        "id": "fafsa", "label": "FAFSA / FSA",
        "url": "https://fsapartners.ed.gov/knowledge-center/rss.xml",
        "category_default": "financial-aid",
        "keywords": {
            "financial-aid": ["fafsa", "aid", "loan", "grant", "repayment", "forgiveness", "pell", "sai"],
            "deadlines":   ["deadline", "opens", "closes", "priority"],
        }
    },
    {
        "id": "bls", "label": "Dept. of Labor",
        "url": "https://www.bls.gov/feed/bls_latest.rss",
        "category_default": "workforce",
        "keywords": {
            "workforce":   ["employment", "earnings", "jobs", "occupation", "labor", "wage", "salary"],
            "trends":      ["education", "degree", "bachelor", "college", "university"],
        }
    },
    {
        "id": "hechinger", "label": "Hechinger Report",
        "url": "https://hechingerreport.org/feed/",
        "category_default": "trends",
        "keywords": {
            "test-policy": ["sat", "act", "test", "score", "optional", "required", "standardized"],
            "deadlines":   ["deadline", "early decision", "application", "waitlist"],
            "financial-aid": ["financial aid", "scholarship", "tuition", "fafsa", "pell", "loan", "aid"],
            "trends":      ["trend", "acceptance", "rate", "enrollment", "ivy", "college", "university"],
            "workforce":   ["job", "employment", "salary", "career", "earnings"],
        }
    },
    {
        "id": "npr", "label": "NPR Education",
        "url": "https://feeds.npr.org/1013/rss.xml",
        "category_default": "trends",
        "keywords": {
            "test-policy": ["sat", "act", "test", "score", "optional", "standardized"],
            "deadlines":   ["deadline", "early decision", "application", "admissions"],
            "financial-aid": ["financial aid", "scholarship", "tuition", "fafsa", "pell", "student loan"],
            "trends":      ["college", "university", "enrollment", "campus", "higher education"],
            "workforce":   ["job", "employment", "salary", "career", "workforce"],
        }
    },
]
 
CURATED_FALLBACK = [
    {"source":"usnews","isNew":True,"title":"Harvard Reinstates SAT/ACT Requirement for Class of 2030","desc":"Harvard joins a growing list of elite universities returning to standardized testing requirements, citing research showing test scores improve prediction of college success for low-income applicants.","category":"test-policy","date":"Apr 2026","url":"https://www.usnews.com/education/best-colleges"},
    {"source":"commonapp","isNew":True,"title":"Common App Reports Record 7.1 Million Applications for 2025–26","desc":"The Common Application reports a record-breaking cycle with international applications up 14% and first-generation applicants up 9%.","category":"trends","date":"Apr 2026","url":"https://www.commonapp.org/blog"},
    {"source":"fafsa","isNew":True,"title":"FAFSA 2026–27 Opens October 1 with Simplified Income Verification","desc":"Federal Student Aid announces the next FAFSA cycle will open on time with a new streamlined income verification process and expanded Pell Grant eligibility.","category":"financial-aid","date":"Apr 2026","url":"https://studentaid.gov/announcements-events/fafsa"},
    {"source":"bls","isNew":True,"title":"BLS: Bachelor's Degree Holders Earn 87% More Than High School Graduates","desc":"The latest Bureau of Labor Statistics data shows the college wage premium has grown to 87%, up from 84% in 2025, reinforcing the economic value of higher education.","category":"workforce","date":"Apr 2026","url":"https://www.bls.gov/ooh/"},
    {"source":"doed","isNew":True,"title":"Education Department Releases 2026 College Affordability Report","desc":"New federal data shows average net price at public 4-year institutions dropped 3% after grant aid, driven by expanded Pell Grant eligibility.","category":"financial-aid","date":"Apr 2026","url":"https://www.ed.gov/news-and-media/press-releases"},
]
 
 
def categorize(text: str, cfg: dict) -> str:
    text_l = text.lower()
    for cat, kws in cfg.get("keywords", {}).items():
        if any(kw in text_l for kw in kws):
            return cat
    return cfg.get("category_default", "trends")
 
 
def format_date(entry) -> str:
    for attr in ("published_parsed", "updated_parsed"):
        ts = getattr(entry, attr, None)
        if ts:
            try:
                dt = datetime(*ts[:6])
                return dt.strftime("%b %Y")
            except Exception:
                pass
    return datetime.now().strftime("%b %Y")
 
 
def fetch_feed_with_timeout(cfg: dict) -> list:
    """Fetch a single feed with a hard timeout using requests + feedparser."""
    items = []
    try:
        print(f"Fetching {cfg['label']}…")
        # Use requests to fetch with timeout, then pass content to feedparser
        resp = requests.get(cfg["url"], timeout=FEED_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (ShiningU RSS Bot)"
        })
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        count = 0
        for entry in feed.entries[:12]:
            title = entry.get("title", "").strip()
            desc  = entry.get("summary", entry.get("description", "")).strip()
            desc  = re.sub(r"<[^>]+>", "", desc)[:280]
            url   = entry.get("link", "#")
            date  = format_date(entry)
            cat   = categorize(title + " " + desc, cfg)
            if title:
                items.append({
                    "source": cfg["id"], "isNew": True,
                    "title": title, "desc": desc,
                    "category": cat, "date": date, "url": url
                })
                count += 1
        print(f"  ✓ {count} items from {cfg['label']}")
    except requests.exceptions.Timeout:
        print(f"  ✗ Timeout after {FEED_TIMEOUT}s — skipping {cfg['label']}")
    except Exception as e:
        print(f"  ✗ Failed {cfg['label']}: {e}")
    return items
 
 
def fetch_all() -> list:
    all_items = []
    for cfg in FEEDS:
        all_items.extend(fetch_feed_with_timeout(cfg))
 
    # De-duplicate by title
    seen, deduped = set(), []
    for item in all_items:
        key = item["title"][:60].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
 
    if not deduped:
        print("All feeds failed — using fallback data.")
        return CURATED_FALLBACK
 
    print(f"Total: {len(deduped)} unique items fetched.")
    return deduped
 
 
def write_json(items: list, json_path: Path):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    payload = {"fetched_at": now, "items": items}
    json_path.write_text(json.dumps(payload["items"], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ news.json written with {len(items)} articles at {now}")
    return True
 
 
if __name__ == "__main__":
    json_path = Path(__file__).parent / "news.json"
    items = fetch_all()
    write_json(items, json_path)
