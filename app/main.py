from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# from app.db.init_db import init_db
from app.api.routes import auth, project, tasks, sessions, journal, users, analytics
import app.models  # noqa: F401 - ensure all models are registered with SQLAlchemy

from app.api.routes.tasks import router as tasks_router, user_tasks_router

app = FastAPI(
    title="CodeFolio",
    description="A portfolio management system for developers to showcase their projects and skills.",
    version="1.0.0",
)

# CORS — required for cookies to work from a browser frontend
# Replace the origin with your actual frontend URL in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # your frontend origin
    allow_credentials=True,  # MUST be True for cookies
    allow_methods=["*"],
    allow_headers=["*"],
)


# init_db()


@app.get("/")
async def read_root():
    return {"message": "Welcome to CodeFolio!"}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(project.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(user_tasks_router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(journal.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
