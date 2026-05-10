import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text

app = FastAPI()
templates = Jinja2Templates(directory="templates")
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


def get_random_video() -> dict | None:
    with engine.connect() as conn:
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


def get_video_count() -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM videos")).scalar() or 0


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    video = get_random_video()
    if not video:
        return templates.TemplateResponse(request=request, name="empty.html", headers={"Cache-Control": "no-store"})
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={"video": video, "video_count": get_video_count()},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/random")
async def api_random():
    video = get_random_video()
    if not video:
        return {"error": "no videos yet"}
    return video
