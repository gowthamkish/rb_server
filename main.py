import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config.database import connect_db, disconnect_db
from app.routes.auth_routes import router as auth_router
from app.routes.convert_routes import router as convert_router
from app.routes.resume_routes import router as resume_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    yield
    await disconnect_db()


app = FastAPI(title="Resume Builder API", version="1.0.0", lifespan=lifespan)

# CORS middleware – mirrors Express cors() config
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CLIENT_URL", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(resume_router, prefix="/api/resumes", tags=["resumes"])
app.include_router(convert_router, prefix="/api/convert", tags=["convert"])


@app.get("/health")
async def health_check():
    return {"message": "Server is running"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"message": "Internal server error"})


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 5000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
