"""Media serving for cut clips (plan/FRONTEND_API_CONTRACT.md §2, media).

Streams ``data/processed/clips/<lecture_id>/<filename>`` with Range support so
browser video players (Streamlit ``st.video`` now, a React ``<video>`` later)
can seek. Filenames are sanitised to their basename and resolved strictly
inside the lecture's clip dir — a non-numeric or traversing value 404s.

Auth note: this route is EXEMPT from the API-key middleware on purpose — a
browser ``<video>``/``st.video`` cannot send an ``X-API-Key`` header. Real
deployments gate /media/* at the reverse proxy / CDN instead.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.config import CLIPS_BASE_DIR

router = APIRouter(prefix="/media")


@router.get("/clips/{lecture_id}/{filename}")
def serve_clip(lecture_id: int, filename: str):
    """Return the clip file (Range-capable via Starlette FileResponse)."""
    name = Path(filename).name
    clip_dir = (CLIPS_BASE_DIR / str(lecture_id)).resolve()
    candidate = (clip_dir / name).resolve()
    base = (CLIPS_BASE_DIR.resolve())
    if not str(candidate).startswith(str(base)) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(candidate, media_type="video/mp4")