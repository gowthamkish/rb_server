"""
Resume CRUD routes – mirrors src/routes/resumeRoutes.ts +
                     src/controllers/resumeController.ts.

All routes require a valid JWT (via get_current_user_id dependency).

POST   /api/resumes/          – create resume
GET    /api/resumes/          – list resumes for current user
GET    /api/resumes/{id}      – get single resume
PUT    /api/resumes/{id}      – update resume
DELETE /api/resumes/{id}      – delete resume
GET    /api/resumes/{id}/download – download (returns resume data + format)
"""
import json
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.config.database import get_db
from app.middleware.auth import get_current_user_id

router = APIRouter()

VALID_TEMPLATES = {"classic", "modern", "creative", "minimal", "ats", "executive"}
VALID_SKILL_LEVELS = {"Beginner", "Intermediate", "Advanced", "Expert"}


# ── Pydantic schemas ───────────────────────────────────────────────────────────
class PersonalInfo(BaseModel):
    fullName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    professionalSummary: Optional[str] = None


class Experience(BaseModel):
    jobTitle: Optional[str] = None
    company: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    currentlyWorking: bool = False
    description: Optional[str] = None


class Education(BaseModel):
    school: Optional[str] = None
    degree: Optional[str] = None
    fieldOfStudy: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    grade: Optional[str] = None


class Skill(BaseModel):
    name: Optional[str] = None
    level: str = "Intermediate"


class CreateResumeRequest(BaseModel):
    title: str
    personalInfo: Optional[dict] = None
    selectedTemplate: str = "classic"
    experiences: Optional[list[dict]] = None
    education: Optional[list[dict]] = None
    skills: Optional[list[dict]] = None


class UpdateResumeRequest(BaseModel):
    title: Optional[str] = None
    personalInfo: Optional[dict] = None
    experiences: Optional[list[dict]] = None
    education: Optional[list[dict]] = None
    skills: Optional[list[dict]] = None
    selectedTemplate: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────
def _to_str_id(oid: Any) -> str:
    return str(oid)


def _serialize_resume(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serialisable dict."""
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    doc["userId"] = str(doc["userId"])
    # Serialise datetime fields
    for key in ("createdAt", "updatedAt"):
        if key in doc and isinstance(doc[key], datetime):
            doc[key] = doc[key].isoformat()
    return doc


def _parse_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except (InvalidId, Exception):
        raise HTTPException(status_code=400, detail="Invalid resume ID")


def _model_to_dict(model: Any) -> dict:
    """Convert a Pydantic model or plain dict to a JSON-serialisable dict.

    Accepts either a `BaseModel` instance (pydantic v2) or a plain `dict`.
    """
    if model is None:
        return {}
    # If it's already a dict (e.g. received from client as JSON), return as-is
    if isinstance(model, dict):
        return model
    # If it's a pydantic model (v2), use model_dump_json / model_dump
    if isinstance(model, BaseModel):
        try:
            return json.loads(model.model_dump_json(exclude_none=True))
        except AttributeError:
            # Fallback for models that implement model_dump instead
            return model.model_dump(exclude_none=True)
    # Try to coerce other types
    try:
        return json.loads(json.dumps(model))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid model payload")


# ── Routes ─────────────────────────────────────────────────────────────────────
@router.post("/", status_code=201)
async def create_resume(
    body: CreateResumeRequest,
    user_id: str = Depends(get_current_user_id),
):
    db = get_db()
    resumes = db["resumes"]

    template = body.selectedTemplate if body.selectedTemplate in VALID_TEMPLATES else "classic"
    now = datetime.now(timezone.utc)

    personal_info = body.personalInfo if body.personalInfo else {}
    experiences = body.experiences if body.experiences is not None else []
    education = body.education if body.education is not None else []
    skills = body.skills if body.skills is not None else []

    doc = {
        "userId": ObjectId(user_id),
        "title": body.title.strip(),
        "personalInfo": personal_info,
        "experiences": experiences,
        "education": education,
        "skills": skills,
        "selectedTemplate": template,
        "createdAt": now,
        "updatedAt": now,
    }

    result = await resumes.insert_one(doc)
    created = await resumes.find_one({"_id": result.inserted_id})

    return {
        "message": "Resume created successfully",
        "resume": _serialize_resume(created),
    }


@router.get("/")
async def get_resumes(user_id: str = Depends(get_current_user_id)):
    db = get_db()
    resumes = db["resumes"]

    cursor = resumes.find({"userId": ObjectId(user_id)})
    docs = [_serialize_resume(doc) async for doc in cursor]
    return docs


@router.get("/{resume_id}")
async def get_resume(
    resume_id: str,
    user_id: str = Depends(get_current_user_id),
):
    db = get_db()
    resumes = db["resumes"]

    oid = _parse_object_id(resume_id)
    doc = await resumes.find_one({"_id": oid})

    if not doc:
        raise HTTPException(status_code=404, detail="Resume not found")
    if str(doc["userId"]) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return _serialize_resume(doc)


@router.put("/{resume_id}")
async def update_resume(
    resume_id: str,
    body: UpdateResumeRequest,
    user_id: str = Depends(get_current_user_id),
):
    db = get_db()
    resumes = db["resumes"]

    oid = _parse_object_id(resume_id)
    doc = await resumes.find_one({"_id": oid})

    if not doc:
        raise HTTPException(status_code=404, detail="Resume not found")
    if str(doc["userId"]) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_fields: dict[str, Any] = {"updatedAt": datetime.now(timezone.utc)}

    if body.title is not None:
        update_fields["title"] = body.title.strip()
    if body.personalInfo is not None:
        update_fields["personalInfo"] = _model_to_dict(body.personalInfo)
    if body.experiences is not None:
        update_fields["experiences"] = [_model_to_dict(e) for e in body.experiences]
    if body.education is not None:
        update_fields["education"] = [_model_to_dict(e) for e in body.education]
    if body.skills is not None:
        update_fields["skills"] = [_model_to_dict(s) for s in body.skills]
    if body.selectedTemplate is not None:
        update_fields["selectedTemplate"] = body.selectedTemplate

    await resumes.update_one({"_id": oid}, {"$set": update_fields})
    updated = await resumes.find_one({"_id": oid})

    return {
        "message": "Resume updated successfully",
        "resume": _serialize_resume(updated),
    }


@router.delete("/{resume_id}")
async def delete_resume(
    resume_id: str,
    user_id: str = Depends(get_current_user_id),
):
    db = get_db()
    resumes = db["resumes"]

    oid = _parse_object_id(resume_id)
    doc = await resumes.find_one({"_id": oid})

    if not doc:
        raise HTTPException(status_code=404, detail="Resume not found")
    if str(doc["userId"]) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    await resumes.delete_one({"_id": oid})
    return {"message": "Resume deleted successfully"}


@router.get("/{resume_id}/download")
async def download_resume(
    resume_id: str,
    format: str = Query(default="pdf"),
    user_id: str = Depends(get_current_user_id),
):
    db = get_db()
    resumes = db["resumes"]

    oid = _parse_object_id(resume_id)
    doc = await resumes.find_one({"_id": oid})

    if not doc:
        raise HTTPException(status_code=404, detail="Resume not found")
    if str(doc["userId"]) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "message": f"Resume download as {format}",
        "resume": _serialize_resume(doc),
        "format": format,
    }
