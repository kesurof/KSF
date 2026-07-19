import shutil
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..core.config import INSTALLED_DIR, DATA_DIR

router = APIRouter()


@router.get("/clean-data")
async def list_clean_data():
    if not DATA_DIR.exists():
        return {"directories": []}
    dirs = []
    for d in sorted(DATA_DIR.iterdir()):
        if not d.is_dir():
            continue
        installed = (INSTALLED_DIR / f"{d.name}.env").exists()
        dirs.append({
            "name": d.name,
            "path": str(d),
            "installed": installed,
        })
    return {"directories": dirs}


@router.delete("/clean-data/{app_name}")
async def clean_data_app(app_name: str):
    if ".." in app_name or "/" in app_name:
        return JSONResponse({"error": "Invalid app name"}, status_code=400)
    target = DATA_DIR / app_name
    if not target.exists():
        return JSONResponse({"error": "Data directory not found"}, status_code=404)
    installed = (INSTALLED_DIR / f"{app_name}.env").exists()
    if installed:
        return JSONResponse({"error": "App is still installed, remove it first"}, status_code=400)
    shutil.rmtree(str(target))
    return {"success": True, "path": str(target)}
