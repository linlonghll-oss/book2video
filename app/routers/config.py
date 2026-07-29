import base64
import binascii
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_db
from app.models.model_config import ModelConfig
from app.schemas.note import ModelConfigCreate, ModelConfigUpdate, ModelConfigResponse
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["model-configs"])

# ---------------------------------------------------------------------------
# Fernet key management
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    """Return a Fernet instance for API key encryption.

    Priority:
    1. settings.ENCRYPTION_KEY (if it looks like a Fernet key)
    2. Auto-generated key stored in storage/.fernet_key
    """
    key = settings.ENCRYPTION_KEY.strip()
    if key:
        # If it's already a valid Fernet key (44-char base64), use directly
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError):
            pass
        # Otherwise derive a key from the passphrase via PBKDF2
        import hashlib
        derived = hashlib.pbkdf2_hmac("sha256", key.encode(), b"book2video-salt", 100_000, dklen=32)
        return Fernet(base64.urlsafe_b64encode(derived))

    # Auto-generate and persist a key file
    key_file = os.path.join("storage", ".fernet_key")
    os.makedirs("storage", exist_ok=True)
    if os.path.isfile(key_file):
        with open(key_file, "r") as f:
            persisted = f.read().strip()
            if persisted:
                return Fernet(persisted.encode())
    # Generate new key
    new_key = Fernet.generate_key()
    with open(key_file, "w") as f:
        f.write(new_key.decode())
    logger.warning("ENCRYPTION_KEY not set — auto-generated key at %s. Set ENCRYPTION_KEY in .env for production.", key_file)
    return Fernet(new_key)


_fernet_instance: Fernet | None = None


def _fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        _fernet_instance = _get_fernet()
    return _fernet_instance


def _encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key using Fernet symmetric encryption."""
    return _fernet().encrypt(api_key.encode()).decode()


def _decrypt_api_key(encrypted: str) -> str | None:
    """Decrypt an API key. Returns None on failure.

    Handles both new Fernet-encrypted and legacy base64-encoded values
    for backward compatibility with existing database rows.
    """
    if not encrypted:
        return None
    # Try Fernet first
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except (InvalidToken, ValueError):
        pass
    # Fallback: legacy base64 encoding (pre-encryption)
    try:
        return base64.b64decode(encrypted.encode()).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None


def _mask_api_key(api_key: str | None) -> str:
    """Return masked API key showing only last 4 characters."""
    if not api_key:
        return "****"
    return "****" + api_key[-4:]


def _to_response(mc: ModelConfig) -> ModelConfigResponse:
    """Convert ORM object to response schema with masked API key."""
    plain = _decrypt_api_key(mc.api_key_encrypted) if mc.api_key_encrypted else None
    return ModelConfigResponse(
        id=mc.id,
        name=mc.name,
        provider=mc.provider,
        model_id=mc.model_id,
        api_key_masked=_mask_api_key(plain),
        params=mc.params,
        is_default=mc.is_default,
        created_at=mc.created_at,
        updated_at=mc.updated_at,
    )


@router.get("/model-configs", response_model=list[ModelConfigResponse])
async def list_model_configs(provider: str | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(ModelConfig).order_by(ModelConfig.updated_at.desc())
    if provider is not None:
        stmt = stmt.where(ModelConfig.provider == provider)
    result = await db.execute(stmt)
    return [_to_response(mc) for mc in result.scalars().all()]


@router.post("/model-configs", response_model=ModelConfigResponse, status_code=201)
async def create_model_config(body: ModelConfigCreate, db: AsyncSession = Depends(get_db)):
    mc = ModelConfig(
        name=body.name,
        provider=body.provider,
        model_id=body.model_id,
        api_key_encrypted=_encrypt_api_key(body.api_key) if body.api_key else None,
        params=body.params,
        is_default=body.is_default or False,
    )

    if mc.is_default:
        await _clear_default_for_provider(db, mc.provider)

    db.add(mc)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Model config with this name already exists")
    await db.refresh(mc)
    return _to_response(mc)


@router.get("/model-configs/{config_id}", response_model=ModelConfigResponse)
async def get_model_config(config_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelConfig).where(ModelConfig.id == config_id))
    mc = result.scalar_one_or_none()
    if mc is None:
        raise HTTPException(status_code=404, detail="Model config not found")
    return _to_response(mc)


@router.patch("/model-configs/{config_id}", response_model=ModelConfigResponse)
async def update_model_config(config_id: int, body: ModelConfigUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelConfig).where(ModelConfig.id == config_id))
    mc = result.scalar_one_or_none()
    if mc is None:
        raise HTTPException(status_code=404, detail="Model config not found")

    update_data = body.model_dump(exclude_unset=True)

    # Handle api_key separately: encrypt before storing
    if "api_key" in update_data:
        raw_key = update_data.pop("api_key")
        mc.api_key_encrypted = _encrypt_api_key(raw_key) if raw_key else None

    # Handle is_default
    is_default_val = update_data.pop("is_default", None)
    if is_default_val is True:
        provider = update_data.get("provider", mc.provider)
        await _clear_default_for_provider(db, provider)
        mc.is_default = True
    elif is_default_val is False:
        mc.is_default = False

    for field, value in update_data.items():
        setattr(mc, field, value)

    await db.commit()
    await db.refresh(mc)
    return _to_response(mc)


@router.delete("/model-configs/{config_id}", status_code=204)
async def delete_model_config(config_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelConfig).where(ModelConfig.id == config_id))
    mc = result.scalar_one_or_none()
    if mc is None:
        raise HTTPException(status_code=404, detail="Model config not found")
    await db.delete(mc)
    await db.commit()


@router.post("/model-configs/{config_id}/set-default", response_model=ModelConfigResponse)
async def set_default_model_config(config_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelConfig).where(ModelConfig.id == config_id))
    mc = result.scalar_one_or_none()
    if mc is None:
        raise HTTPException(status_code=404, detail="Model config not found")

    await _clear_default_for_provider(db, mc.provider)
    mc.is_default = True
    await db.commit()
    await db.refresh(mc)
    return _to_response(mc)


async def _clear_default_for_provider(db: AsyncSession, provider: str):
    """Remove is_default flag from all configs of the given provider."""
    result = await db.execute(
        select(ModelConfig).where(ModelConfig.provider == provider, ModelConfig.is_default == True)
    )
    for existing in result.scalars().all():
        existing.is_default = False


@router.post("/model-configs/{config_id}/test")
async def test_model_config(config_id: int, db: AsyncSession = Depends(get_db)):
    """Test whether a model config is properly set up by making a minimal API call."""
    import httpx
    from app.config import settings

    result = await db.execute(select(ModelConfig).where(ModelConfig.id == config_id))
    mc = result.scalar_one_or_none()
    if mc is None:
        raise HTTPException(status_code=404, detail="Model config not found")

    api_key = _decrypt_api_key(mc.api_key_encrypted) if mc.api_key_encrypted else None
    base_url = (mc.params or {}).get("base_url")
    model_id = mc.model_id
    provider = mc.provider

    # --- LLM test ---
    if provider == "llm":
        if not api_key and not (base_url and "11434" in str(base_url)):
            return {"ok": False, "message": "未配置 API Key"}
        url = f"{(base_url or settings.LLM_BASE_URL).rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 5,
            "temperature": 0,
        }
        try:
            verify_ssl = "coze" not in str(base_url)
            async with httpx.AsyncClient(timeout=30.0, verify=verify_ssl) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    return {"ok": True, "message": f"LLM 连通正常（{model_id}）"}
                elif resp.status_code == 401:
                    return {"ok": False, "message": "API Key 无效或已过期"}
                else:
                    return {"ok": False, "message": f"请求失败（HTTP {resp.status_code}）：{resp.text[:200]}"}
        except httpx.ConnectError:
            return {"ok": False, "message": "无法连接服务器，请检查 Base URL 和网络"}
        except Exception as exc:
            return {"ok": False, "message": f"连接异常：{str(exc)[:200]}"}

    # --- Image test ---
    if provider == "image":
        if not api_key:
            return {"ok": False, "message": "未配置 API Key"}
        url = f"{(base_url or settings.IMAGE_BASE_URL).rstrip('/')}/images/generations"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_id,
            "prompt": "a red dot",
            "image_size": "1024x1024",
            "num_inference_steps": 1,
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    return {"ok": True, "message": f"图片模型连通正常（{model_id}）"}
                elif resp.status_code == 401:
                    return {"ok": False, "message": "API Key 无效或已过期"}
                else:
                    return {"ok": False, "message": f"请求失败（HTTP {resp.status_code}）：{resp.text[:200]}"}
        except httpx.ConnectError:
            return {"ok": False, "message": "无法连接服务器，请检查 Base URL 和网络"}
        except Exception as exc:
            return {"ok": False, "message": f"连接异常：{str(exc)[:200]}"}

    # --- Video test ---
    if provider == "video":
        if not api_key:
            return {"ok": False, "message": "未配置 API Key"}
        url = f"{(base_url or settings.VIDEO_BASE_URL).rstrip('/')}/video/submit"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": model_id, "prompt": "a calm scenic video", "image_size": "1280x720"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    return {"ok": True, "message": f"视频模型连通正常（{model_id}）"}
                elif resp.status_code == 401:
                    return {"ok": False, "message": "API Key 无效或已过期"}
                else:
                    error_text = resp.text[:300]
                    if "insufficient" in error_text.lower() or "balance" in error_text.lower():
                        return {"ok": False, "message": "API Key 有效，但余额不足"}
                    return {"ok": False, "message": f"请求失败（HTTP {resp.status_code}）：{error_text}"}
        except httpx.ConnectError:
            return {"ok": False, "message": "无法连接服务器，请检查 Base URL 和网络"}
        except Exception as exc:
            return {"ok": False, "message": f"连接异常：{str(exc)[:200]}"}

    # --- TTS test ---
    if provider == "tts":
        try:
            import edge_tts
            communicate = edge_tts.Communicate("测试", model_id)
            return {"ok": True, "message": f"TTS 语音可用（{model_id}）"}
        except Exception as exc:
            return {"ok": False, "message": f"TTS 语音不可用：{str(exc)[:200]}"}

    return {"ok": False, "message": f"未知的 provider 类型：{provider}"}
