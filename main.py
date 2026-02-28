import os
import traceback
from contextlib import asynccontextmanager

# load_dotenv() MUST run before any app.* imports so that modules which read
# env vars at import time (e.g. JWT_SECRET in auth.py / auth_routes.py) pick
# up the values from .env.
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app.config.database import connect_db, disconnect_db  # noqa: E402
from app.routes.auth_routes import router as auth_router  # noqa: E402
from app.routes.convert_routes import router as convert_router  # noqa: E402
from app.routes.resume_routes import router as resume_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect to DB but don't fail the whole app startup if connection fails.
    # Some hosting environments can cause transient TLS/network errors during
    # startup; allow the app to start so the process binds the port and logs
    # the underlying error for debugging.
    _connected = False
    try:
        await connect_db()
        _connected = True
    except Exception as exc:
        # Print full traceback to logs so Render/hosting shows the root cause.
        import traceback

        print("Warning: failed to connect to MongoDB during startup:", exc)
        traceback.print_exc()

    try:
        yield
    finally:
        if _connected:
            try:
                await disconnect_db()
            except Exception:
                pass


app = FastAPI(title="Resume Builder API", version="1.0.0", lifespan=lifespan)

# CORS middleware – allow one or more client origins.
# Read `CLIENT_URL` from env; support comma-separated values for multiple
# client hosts (e.g. `http://localhost:5173,https://rb-client.vercel.app`).
_origins_env = os.getenv("CLIENT_URL", "http://localhost:5173")
_origins = [o.strip() for o in _origins_env.split(",") if o.strip()]
# Ensure common deployment URL is allowed (helpful when CLIENT_URL wasn't set)
if "https://rb-client.vercel.app" not in _origins:
    _origins.append("https://rb-client.vercel.app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
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
    # Don't swallow HTTPException – let FastAPI handle it with the correct status code
    if isinstance(exc, HTTPException):
        raise exc
    # Log the real error so it's visible in Render / hosting logs
    print(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"message": "Internal server error"})


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 5000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
