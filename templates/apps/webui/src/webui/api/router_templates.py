from fastapi import APIRouter
from ..core.state import list_available_templates

router = APIRouter()


@router.get("")
async def get_templates():
    templates = list_available_templates()
    return {"templates": templates}
