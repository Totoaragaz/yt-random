import os
import pathlib

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text

app = FastAPI()
templates = Jinja2Templates(directory="templates")
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

pathlib.Path("static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


def get_random_video(exclude: list[str] | None = None) -> dict | None:
    with engine.connect() as conn:
        if exclude:
            row = conn.execute(
                text("""
                    SELECT id, title, channel_id, language, view_count, search_date_window
                    FROM videos
                    WHERE id != ALL(:exclude)
                    ORDER BY RANDOM()
                    LIMIT 1
                """),
                {"exclude": exclude}
            ).fetchone()
        else:
            row = conn.execute(
                text("""
                    SELECT id, title, channel_id, language, view_count, search_date_window
                    FROM videos
                    ORDER BY RANDOM()
                    LIMIT 1
                """)
            ).fetchone()
    if not row:
        return None
    return {
        "id": row[0], "title": row[1], "channel_id": row[2],
        "language": row[3], "view_count": row[4], "search_date_window": row[5],
    }


def get_video_by_id(video_id: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT id, title, channel_id, language, view_count, search_date_window
                FROM videos WHERE id = :id
            """),
            {"id": video_id}
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0], "title": row[1], "channel_id": row[2],
        "language": row[3], "view_count": row[4], "search_date_window": row[5],
    }


def get_video_count() -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM videos")).scalar() or 0


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    video_id = request.query_params.get("v")
    video = get_video_by_id(video_id) if video_id else None
    if not video:
        video = get_random_video()
    if not video:
        return templates.TemplateResponse(request=request, name="empty.html", headers={"Cache-Control": "no-store"})
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={"video": video, "video_count": get_video_count()},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/google519ec88911f9452b.html", response_class=PlainTextResponse)
async def google_verify():
    return "google-site-verification: google519ec88911f9452b.html"


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return """User-agent: *
Allow: /

Sitemap: https://ytrandom.com/sitemap.xml
"""


@app.get("/sitemap.xml")
async def sitemap():
    return Response(
        content="""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://ytrandom.com/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>""",
        media_type="application/xml",
    )


@app.get("/api/random")
async def api_random(request: Request):
    exclude_param = request.query_params.get("exclude", "")
    exclude = [v for v in exclude_param.split(",") if v] or None
    video = get_random_video(exclude=exclude)
    if not video:
        return {"error": "no videos yet"}
    return video
