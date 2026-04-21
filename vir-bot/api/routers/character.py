"""角色卡管理 API"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from vir_bot.core.character import CharacterCard, load_character_card
from vir_bot.config import get_config

router = APIRouter()


class CharacterCardResponse(BaseModel):
    name: str
    description: str
    personality: str
    world_info: str
    scenario: str
    first_message: str
    example_dialogue: str
    extensions: dict


class CharacterUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    personality: str | None = None
    world_info: str | None = None
    scenario: str | None = None
    first_message: str | None = None
    example_dialogue: str | None = None
    extensions: dict | None = None


def get_current_card() -> CharacterCard:
    config = get_config()
    return load_character_card(config.character.card_path)


@router.get("/", response_model=CharacterCardResponse)
async def get_character():
    card = get_current_card()
    return CharacterCardResponse(
        name=card.name,
        description=card.description,
        personality=card.personality,
        world_info=card.world_info,
        scenario=card.scenario,
        first_message=card.first_message,
        example_dialogue=card.example_dialogue,
        extensions=card.extensions,
    )


@router.post("/")
async def update_character(req: CharacterUpdateRequest):
    card = get_current_card()
    for field, value in req.model_dump(exclude_none=True).items():
        if hasattr(card, field):
            setattr(card, field, value)
    config = get_config()
    card.save(config.character.card_path)
    return {"status": "ok", "message": "角色卡已更新"}


@router.post("/upload")
async def upload_character(file: UploadFile = File(...)):
    import json
    content = await file.read()
    try:
        data = json.loads(content)
        card = CharacterCard.from_json(data)
        config = get_config()
        card.save(config.character.card_path)
        return {"status": "ok", "name": card.name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"上传失败: {e}")