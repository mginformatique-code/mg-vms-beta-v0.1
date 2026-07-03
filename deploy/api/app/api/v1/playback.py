"""Relecture & export : URLs signées S3/MinIO vers les segments enregistrés."""
from uuid import UUID

import boto3
from botocore.client import Config
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_permission
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Recording, User
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/playback", tags=["playback"])


def _s3_client():
    s = get_settings()
    return boto3.client(
        "s3", endpoint_url=s.S3_ENDPOINT,
        aws_access_key_id=s.S3_ACCESS_KEY, aws_secret_access_key=s.S3_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )


@router.get("/{recording_id}/url")
async def playback_url(recording_id: UUID,
                       user: User = Depends(require_permission("view_recordings")),
                       db: AsyncSession = Depends(get_db)):
    rec = await db.get(Recording, recording_id)
    if not rec:
        raise HTTPException(404, "Enregistrement introuvable")
    s = get_settings()
    url = _s3_client().generate_presigned_url(
        "get_object", Params={"Bucket": s.S3_BUCKET, "Key": rec.path}, ExpiresIn=3600,
    )
    return {"recording_id": str(rec.id), "url": url, "expires_in": 3600}


@router.get("/{recording_id}/export")
async def export_url(recording_id: UUID,
                     user: User = Depends(require_permission("export_files")),
                     db: AsyncSession = Depends(get_db)):
    rec = await db.get(Recording, recording_id)
    if not rec:
        raise HTTPException(404, "Enregistrement introuvable")
    s = get_settings()
    url = _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": s.S3_BUCKET, "Key": rec.path,
                "ResponseContentDisposition": f'attachment; filename="{rec.path.split("/")[-1]}"'},
        ExpiresIn=900,
    )
    return {"recording_id": str(rec.id), "download_url": url, "expires_in": 900}
