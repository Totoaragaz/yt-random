import os
import random

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text

app = FastAPI()
templates = Jinja2Templates(directory="templates")
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


def get_random_video() -> dict | None:
    with engine.connect() as conn:
        max_id = conn.execute(text("SELECT MAX(serial_id) FROM videos")).scalar()
        if not max_id:
            return None
        floor = random.randint(1, max_id)
        row = conn.execute(
            text("""
                SELECT id, title, channel_id, language, view_count
                FROM videos
                WHERE serial_id >= :floor
                ORDER BY serial_id
                LIMIT 1
            """),
            {"floor": floor},
        ).fetchone()
        if not row:
            # floor landed past the last row — grab the last one
            row = conn.execute(
                text("SELECT id, title, channel_id, language, view_count FROM videos ORDER BY serial_id DESC LIMIT 1")
            ).fetchone()
    if not row:
        return None
    return {"id": row[0], "title": row[1], "channel_id": row[2], "language": row[3], "view_count": row[4]}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    video = get_random_video()
    if not video:
        return templates.TemplateResponse(request=request, name="empty.html", headers={"Cache-Control": "no-store"})
    return templates.TemplateResponse(request=request, name="index.html", context={"video": video}, headers={"Cache-Control": "no-store"})


@app.get("/api/random")
async def api_random():
    video = get_random_video()
    if not video:
        return {"error": "no videos yet"}
    return video
