import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import catalog
from app.chat import process_chat
from app.models import ChatRequest, ChatResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s  %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Loading catalog and building index...")
    try:
        catalog.load_catalog()
        catalog.build_index()
        log.info("Startup complete.")
    except Exception as exc:
        log.error(f"Startup failed: {exc}", exc_info=True)
        raise
    yield
    log.info("Shutting down.")


app = FastAPI(
    title="SHL Assessment Advisor",
    description="Conversational AI agent for discovering SHL assessments.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return process_chat(request)
