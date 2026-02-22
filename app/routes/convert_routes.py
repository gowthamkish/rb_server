"""
Document conversion route – mirrors src/routes/convertRoutes.ts +
                            src/controllers/convertController.ts.

POST /api/convert/
    Accepts a .doc or .docx file upload, extracts plain text and returns it.

    .docx: extracted via python-docx (paragraph-by-paragraph)
    .doc : first converted to .docx with LibreOffice (headless), then same path
"""
import io
import os
import shutil
import subprocess
import tempfile

from docx import Document
from fastapi import APIRouter, HTTPException, UploadFile

router = APIRouter()

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB guard


def _extract_text_from_docx(buffer: bytes) -> str:
    """Extract plain text from a .docx buffer using python-docx."""
    doc = Document(io.BytesIO(buffer))
    lines: list[str] = []
    for para in doc.paragraphs:
        lines.append(para.text)
    return "\n".join(lines)


def _convert_doc_to_docx(buffer: bytes) -> bytes:
    """
    Convert a legacy .doc buffer to .docx using LibreOffice (headless).
    Mirrors the libreoffice-convert npm package behaviour.
    """
    if not shutil.which("libreoffice"):
        raise HTTPException(
            status_code=500,
            detail="Server cannot convert .doc files (libreoffice not found)",
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.doc")
        with open(input_path, "wb") as f:
            f.write(buffer)

        try:
            subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    tmpdir,
                    input_path,
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"LibreOffice conversion failed: {exc.stderr.decode(errors='replace')}",
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(
                status_code=500,
                detail="LibreOffice conversion timed out",
            )

        output_path = os.path.join(tmpdir, "input.docx")
        if not os.path.exists(output_path):
            raise HTTPException(
                status_code=500,
                detail="LibreOffice did not produce output file",
            )

        with open(output_path, "rb") as f:
            return f.read()


@router.post("/")
async def convert_doc(file: UploadFile):
    """
    Upload a .doc or .docx file and receive extracted plain text.
    """
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    filename: str = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in {"doc", "docx"}:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    buffer = await file.read()
    if len(buffer) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    docx_buffer: bytes

    if ext == "docx":
        docx_buffer = buffer
    else:
        # .doc → .docx via LibreOffice
        try:
            docx_buffer = _convert_doc_to_docx(buffer)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Server cannot convert .doc files: {exc}",
            )

    try:
        text = _extract_text_from_docx(docx_buffer)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract text from document: {exc}",
        )

    return {"text": text}
