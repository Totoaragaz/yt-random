# TODOs

## Setup requirements

### cookies.txt is mandatory for the crawl phase
`collect.py` requires a `cookies.txt` (Netscape format) at the project root. Without it the
crawl phase aborts. YouTube rate-limits unauthenticated scraping aggressively; authenticated
requests from a neutral account are stable.

Steps to refresh cookies:
1. Sign into the YouTube account in Chrome
2. Export with "Get cookies.txt LOCALLY" extension → save as `cookies.txt` in project root
3. Cookies typically last weeks; re-export if the crawl starts failing with 429s again

The account should be neutral (minimal watch history) to avoid personalized recommendations
skewing the crawled video pool.

## Data quality

### duration_seconds and view_count are always NULL
Every video in the DB has NULL for these two fields. They're not returned by `search.list`
(only `snippet` part is fetched in the API phase), and the crawl phase only extracts
title + video ID from the recommendations sidebar.

Fix options:
- Add a separate daily enrichment step: batch-fetch up to 10,000 video IDs via `videos.list`
  with `part=statistics,contentDetails` (costs 1 unit per call, 50 IDs per call = 200 calls
  for 10,000 videos = 200 units). Run after collect.py.
- Or: extract duration from the thumbnail overlay badge text (e.g. "8:01") during the crawl
  phase — already available in the lockupViewModel, just not currently parsed.

## Frontend

### Optional filters: language and upload date
The random SELECT currently ignores all metadata. Add optional query parameters:
- `?lang=ro` — filter to videos where `language = 'ro'`
- `?before=2015` — filter to videos where `search_date_window < '2015-01-01'`
- `?after=2010` — filter to videos where `search_date_window > '2010-01-01'`

Implementation: add a small filter bar to the frontend, pass params to `/api/random`,
modify `get_random_video()` to accept optional WHERE clauses.

Note: language is NULL for ~40% of videos (short titles, low confidence). Filtering by
language will miss those. Consider a "surprise me" default that ignores language.

### channel_id is NULL for all crawled videos
The recommendations sidebar (lockupViewModel) doesn't expose channel_id directly — only
video ID and title are extracted. API-phase videos have channel_id from the `snippet`.

Fix: during the enrichment step described above (videos.list with statistics,contentDetails),
also request `part=snippet` which includes `channelId`. One enrichment call covers
duration, view_count, AND channel_id for all videos at once.

## Performance

### Intra-run seed deduplication
Two API searches in the same run can return the same video ID. Both pass the DB pre-check
and both get crawled. Rare at current scale (maybe 5-10/run), fix when measurable.
One line: `seeds = list({v['id']: v for v in all_seeds}.values())` before the crawl phase.
