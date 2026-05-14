# TODOs

## Up next — Growth

### SEO
Add to index.html `<head>`:
- `<title>ytrandom — random YouTube videos</title>`
- Open Graph tags: `og:title`, `og:description`, `og:image` (static screenshot)
- `<meta name="description" content="...">`
- `robots.txt` and `sitemap.xml` (homepage only)

After SEO is live, make the GitHub repo private.

### Ko-fi support button
Add a "Support me" link/button pointing to the Ko-fi page. Tasteful placement —
footer or corner, not intrusive. No paywall, no gating — all features stay free.

### Filters (free feature)
Add `?lang=ro`, `?before=2015`, `?after=2010`, `?min_views=`, `?max_duration=`
query params to `/api/random`. Small filter bar on the frontend.
- ~40% of videos have NULL language — treat NULL as "any" so those still surface
- `duration_seconds` and `view_count` are now populated for all videos, so numeric
  filters are ready to implement
- Consider a "surprise me" default (no filters) as the landing state

---

## Decisions made

### Ads — ruled out
YouTube ToS Section 4 prohibits ads adjacent to the embedded player.
Not pursuing AdSense or any ad placement.

### Paywall — ruled out
Filters and all other features will be free. Monetization is Ko-fi (voluntary).

### Crawler — not needed
Pool is large enough from the API search phase alone (~295 new videos/day).
Crawl mode (`python collect.py --crawl-only`) remains in the codebase but
is not used. If reintroduced later, use a `seeds.json` of ~100 manually
curated videos across categories/languages/years instead of crawling from
recommendations — prevents topical clustering.

---

## Backlog

### Intra-run seed deduplication
Two API searches in the same run can return the same video ID. Rare but fixable
in one line before the DB upsert loop.
