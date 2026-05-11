import asyncio
import json
import logging
import os
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
from langdetect import DetectorFactory, LangDetectException, detect_langs
from sqlalchemy import create_engine, text

DetectorFactory.seed = 0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # suppresses URLs containing API key

API_KEY = os.environ["YOUTUBE_API_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]
CHECKPOINT_FILE = Path("/tmp/collect_checkpoint.json")
WORDLIST_FILE = Path("wordlist.json")

YOUTUBE_CATEGORY_MAP = {
    "Film & Animation": 1, "Autos & Vehicles": 2, "Music": 10,
    "Pets & Animals": 15, "Sports": 17, "Short Movies": 18,
    "Travel & Events": 19, "Gaming": 20, "Videoblogging": 21,
    "People & Blogs": 22, "Comedy": 23, "Entertainment": 24,
    "News & Politics": 25, "Howto & Style": 26, "Education": 27,
    "Science & Technology": 28, "Nonprofits & Activism": 29,
}

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_duration(duration: str) -> int | None:
    if not duration:
        return None
    m = re.match(r'P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not m:
        return None
    days    = int(m.group(1) or 0)
    hours   = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    seconds = int(m.group(4) or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


# ---------------------------------------------------------------------------
# Distance / diversity
# ---------------------------------------------------------------------------

def distance(a: dict, b: dict) -> float:
    cat_a, cat_b = a.get("category_id"), b.get("category_id")
    cat_dist = 0.0 if (cat_a is None or cat_b is None or cat_a == cat_b) else 1.0

    lang_a, lang_b = a.get("language"), b.get("language")
    lang_dist = 0.0 if (lang_a is None or lang_b is None or lang_a == lang_b) else 1.0

    words_a = set((a.get("title") or "").lower().split())
    words_b = set((b.get("title") or "").lower().split())
    union = words_a | words_b
    jaccard_dist = 1.0 - (len(words_a & words_b) / len(union)) if union else 0.0

    return 0.5 * cat_dist + 0.3 * lang_dist + 0.2 * jaccard_dist


def select_diverse(candidates: list[dict], n: int = 3) -> list[dict]:
    if not candidates:
        return []
    if len(candidates) <= n:
        return list(candidates)
    selected = [random.choice(candidates)]
    selected_ids = {selected[0]["id"]}
    remaining = [v for v in candidates if v["id"] not in selected_ids]
    while len(selected) < n and remaining:
        scores = [min(distance(c, s) for s in selected) for c in remaining]
        pick = remaining[scores.index(max(scores))]
        selected.append(pick)
        selected_ids.add(pick["id"])
        remaining = [v for v in remaining if v["id"] not in selected_ids]
    return selected


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(title: str) -> str | None:
    if not title or len(title.split()) < 3:
        return None
    try:
        results = detect_langs(title)
        if results and results[0].prob >= 0.8:
            return results[0].lang
    except LangDetectException:
        pass
    return None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)


def upsert_video(engine, video: dict) -> bool:
    sql = text("""
        INSERT INTO videos (
            id, title, channel_id, category_id, language,
            duration_seconds, view_count, discovered_via,
            search_term, search_date_window
        ) VALUES (
            :id, :title, :channel_id, :category_id, :language,
            :duration_seconds, :view_count, :discovered_via,
            :search_term, :search_date_window
        )
        ON CONFLICT (id) DO NOTHING
    """)
    with engine.begin() as conn:
        result = conn.execute(sql, video)
        return result.rowcount > 0


def backfill_category(engine, video_id: str, category_id: int | None, language: str | None) -> None:
    sql = text("""
        UPDATE videos
        SET category_id = COALESCE(category_id, :category_id),
            language    = COALESCE(language,    :language)
        WHERE id = :id
    """)
    with engine.begin() as conn:
        conn.execute(sql, {"id": video_id, "category_id": category_id, "language": language})


def get_uncrawled_seeds(engine, limit: int = 50) -> list[dict]:
    sql = text("""
        SELECT id, title, search_term, search_date_window
        FROM videos
        WHERE id NOT IN (
            SELECT DISTINCT discovered_via FROM videos WHERE discovered_via IS NOT NULL
        )
        ORDER BY collected_at DESC
        LIMIT :limit
    """)
    with engine.begin() as conn:
        rows = conn.execute(sql, {"limit": limit}).fetchall()
    return [
        {
            "id": row[0], "title": row[1],
            "search_term": row[2], "search_date_window": row[3],
            "category_id": None, "language": None,
        }
        for row in rows
    ]


def get_existing_ids(engine, video_ids: list[str]) -> set[str]:
    if not video_ids:
        return set()
    sql = text("SELECT id FROM videos WHERE id = ANY(:ids)")
    with engine.begin() as conn:
        rows = conn.execute(sql, {"ids": list(video_ids)}).fetchall()
    return {row[0] for row in rows}


# ---------------------------------------------------------------------------
# API phase
# ---------------------------------------------------------------------------

def random_date_window() -> str:
    start = date(2005, 4, 23)
    end = date.today() - timedelta(days=8)  # leave room for 7-day window
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).isoformat()


async def search_batch(
    client: httpx.AsyncClient,
    word: str,
    date_window: str,
    index: int,
) -> list[dict] | None:
    after = date_window
    before = (date.fromisoformat(after) + timedelta(days=7)).isoformat()

    for attempt in range(3):
        try:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": word,
                    "type": "video",
                    "maxResults": 50,
                    "publishedAfter": f"{after}T00:00:00Z",
                    "publishedBefore": f"{before}T00:00:00Z",
                    "key": API_KEY,
                },
                timeout=15.0,
            )
            if resp.status_code == 403:
                log.critical("Quota exceeded (403). Stopping. Checkpoint preserved.")
                return None  # signals caller to stop
            resp.raise_for_status()

            items = resp.json().get("items", [])
            candidates = [
                {
                    "id": item["id"]["videoId"],
                    "title": item["snippet"].get("title", ""),
                    "channel_id": item["snippet"].get("channelId"),
                    "category_id": None,
                    "language": detect_language(item["snippet"].get("title", "")),
                    "duration_seconds": None,
                    "view_count": None,
                    "discovered_via": None,
                    "search_term": word,
                    "search_date_window": date_window,
                }
                for item in items
                if item.get("id", {}).get("videoId")
            ]
            return select_diverse(candidates, n=3)

        except httpx.HTTPStatusError:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
            else:
                log.warning(f"Search {index} ({word} {date_window}): failed after 3 attempts")
                return []
        except Exception as exc:
            log.warning(f"Search {index}: {exc}")
            return []

    return []


# ---------------------------------------------------------------------------
# Crawl phase — direct YouTube page scraping (no yt-dlp)
# ---------------------------------------------------------------------------

def _extract_yt_initial_data(html: str) -> dict | None:
    m = re.search(r"ytInitialData\s*=\s*(\{)", html)
    if not m:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html, m.start(1))
        return data
    except Exception:
        return None


async def get_suggested_videos(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    video_id: str,
) -> list[dict]:
    try:
        async with semaphore:
            await asyncio.sleep(random.uniform(2.0, 4.0))
            resp = await client.get(
                f"https://www.youtube.com/watch?v={video_id}",
                timeout=15.0,
            )
        if resp.status_code != 200:
            return []
        data = _extract_yt_initial_data(resp.text)
        if not data:
            return []
        contents = (
            data.get("contents", {})
            .get("twoColumnWatchNextResults", {})
            .get("secondaryResults", {})
            .get("secondaryResults", {})
            .get("results", [])
        )
        videos = []
        for section in contents:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                lvm = item.get("lockupViewModel", {})
                if lvm.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
                    continue
                vid_id = lvm.get("contentId", "")
                if not vid_id or len(vid_id) != 11:
                    continue
                title = (
                    lvm.get("metadata", {})
                    .get("lockupMetadataViewModel", {})
                    .get("title", {})
                    .get("content", "")
                )
                videos.append({"id": vid_id, "title": title})
        return videos
    except Exception as exc:
        log.debug(f"scrape {video_id}: {exc}")
        return []


async def crawl_seed(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    engine,
    seed: dict,
    health_failures: list[int],
) -> list[dict]:
    suggested = await get_suggested_videos(client, semaphore, seed["id"])
    if not suggested:
        health_failures[0] += 1
        return []

    candidates = [
        {
            "id": v["id"],
            "title": v["title"],
            "channel_id": None,
            "category_id": None,
            "language": detect_language(v["title"]),
            "duration_seconds": None,
            "view_count": None,
            "discovered_via": seed["id"],
            "search_term": seed["search_term"],
            "search_date_window": seed["search_date_window"],
        }
        for v in suggested
    ]

    picks = select_diverse([seed] + candidates, n=2)
    return [p for p in picks if p["id"] != seed["id"]][:1]


# ---------------------------------------------------------------------------
# Enrich phase — fill view_count, duration_seconds, and fix corrupted titles
# ---------------------------------------------------------------------------

async def enrich_videos(engine, client: httpx.AsyncClient) -> None:
    sql = text("SELECT id FROM videos WHERE view_count IS NULL ORDER BY collected_at DESC")
    with engine.begin() as conn:
        rows = conn.execute(sql).fetchall()

    video_ids = [row[0] for row in rows]
    if not video_ids:
        log.info("Enrich: nothing to enrich")
        return

    log.info(f"Enrich: {len(video_ids)} videos to enrich")

    updated = 0
    call_count = 0
    MAX_CALLS = 100

    update_sql = text("""
        UPDATE videos
        SET title            = :title,
            view_count       = :view_count,
            duration_seconds = :duration_seconds
        WHERE id = :id
    """)

    for i in range(0, len(video_ids), 50):
        if call_count >= MAX_CALLS:
            log.warning(f"Enrich: hit {MAX_CALLS}-call cap, stopping")
            break

        batch = video_ids[i:i + 50]
        try:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(batch),
                    "key": API_KEY,
                },
                timeout=15.0,
            )
            call_count += 1

            if resp.status_code == 403:
                log.critical("Enrich: quota exceeded (403). Stopping.")
                break
            resp.raise_for_status()

            items = resp.json().get("items", [])
            with engine.begin() as conn:
                for item in items:
                    view_count_str = item.get("statistics", {}).get("viewCount")
                    conn.execute(update_sql, {
                        "id":               item["id"],
                        "title":            item.get("snippet", {}).get("title") or "",
                        "view_count":       int(view_count_str) if view_count_str else None,
                        "duration_seconds": parse_duration(
                            item.get("contentDetails", {}).get("duration") or ""
                        ),
                    })
                    updated += 1

        except Exception as exc:
            log.warning(f"Enrich: batch {i // 50} failed: {exc}")

    log.info(f"Enrich: updated {updated} videos in {call_count} API calls")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    crawl_only = "--crawl-only" in sys.argv
    engine = get_engine()

    seeds: list[dict] = []
    api_new = 0

    if crawl_only:
        log.info("Crawl-only mode: loading uncrawled seeds from DB")
        seeds = get_uncrawled_seeds(engine, limit=1)
        log.info(f"Found {len(seeds)} uncrawled seeds")
    else:
        words = json.loads(WORDLIST_FILE.read_text())

        # Resume from checkpoint if present
        completed: set[int] = set()
        if CHECKPOINT_FILE.exists():
            try:
                completed = set(json.loads(CHECKPOINT_FILE.read_text()))
                log.info(f"Resuming: {len(completed)}/99 searches already done")
            except Exception:
                completed = set()

        # Deterministic task list — same words/dates if run is resumed today
        rng = random.Random(str(date.today()))
        tasks = [
            (i, rng.choice(words), random_date_window())
            for i in range(99)  # 99 searches × 100 units = 9900; leaves 100 for enrich
        ]

        quota_hit = False
        async with httpx.AsyncClient() as client:
            for i, word, date_window in tasks:
                if i in completed:
                    continue
                results = await search_batch(client, word, date_window, i)
                if results is None:
                    quota_hit = True
                    break
                for video in results:
                    if upsert_video(engine, video):
                        api_new += 1
                        seeds.append(video)
                completed.add(i)
                CHECKPOINT_FILE.write_text(json.dumps(sorted(completed)))
                if i < 98:
                    await asyncio.sleep(1)

        CHECKPOINT_FILE.unlink(missing_ok=True)
        if quota_hit:
            log.warning(f"Quota exhausted after {len(seeds)} seeds.")
        else:
            log.info(f"API phase done: {api_new} new videos from {len(seeds)} seeds")

        if not quota_hit:
            async with httpx.AsyncClient() as client:
                await enrich_videos(engine, client)

        return

    # Everything below only runs via: python collect.py --crawl-only

    # Deduplicate seeds within this run
    seen: set[str] = set()
    crawl_targets = []
    for s in seeds:
        if s["id"] not in seen:
            seen.add(s["id"])
            crawl_targets.append(s)

    log.info(f"Crawl phase: scraping {len(crawl_targets)} seeds")
    health_failures = [0]
    crawl_new = 0

    crawl_semaphore = asyncio.Semaphore(3)  # max 3 concurrent page fetches

    cookies: dict[str, str] = {}
    cookies_file = Path("cookies.txt")
    if cookies_file.exists():
        import http.cookiejar
        jar = http.cookiejar.MozillaCookieJar()
        jar.load(str(cookies_file), ignore_discard=True, ignore_expires=True)
        cookies = {c.name: c.value for c in jar if "youtube.com" in c.domain}
        log.info(f"Loaded {len(cookies)} YouTube cookies")
    else:
        log.info("No cookies.txt — scraping without auth")

    async with httpx.AsyncClient(
        headers=SCRAPE_HEADERS,
        cookies=cookies,
        follow_redirects=True,
    ) as crawl_client:
        crawl_results = await asyncio.gather(
            *[crawl_seed(crawl_client, crawl_semaphore, engine, seed, health_failures) for seed in crawl_targets],
            return_exceptions=True,
        )

    for batch in crawl_results:
        if isinstance(batch, Exception):
            log.debug(f"Crawl error: {batch}")
            continue
        for video in batch:
            if upsert_video(engine, video):
                crawl_new += 1

    total = api_new + crawl_new
    failure_rate = health_failures[0] / max(len(crawl_targets), 1)

    if failure_rate > 0.2:
        log.critical(
            f"Crawl health check FAILED: {health_failures[0]}/{len(crawl_targets)} "
            f"seeds returned 0 suggestions ({failure_rate:.0%}). "
            "YouTube may be blocking scraping — check cookies.txt."
        )

    log.info(
        f"Done. API seeds: {api_new} | Crawled: {crawl_new} | "
        f"Total new: {total} | Crawl failures: {health_failures[0]}/{len(crawl_targets)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
