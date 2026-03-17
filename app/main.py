from fastapi import FastAPI
from app.db.init_db import init_db
from app.api.routes import auth

app = FastAPI(
    title="CodeFolio",
    description="A portfolio management system for developers to showcase their projects and skills.",
    version="1.0.0",
)

init_db()


@app.get("/")
async def read_root():
    return {"message": "Welcome to CodeFolio!"}


app.include_router(auth.router, prefix="/api")
