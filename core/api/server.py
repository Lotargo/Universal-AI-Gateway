import os
import logging
from contextlib import asynccontextmanager
import httpx
from dotenv import load_dotenv

load_dotenv()
import redis.asyncio as redis
from aiokafka import AIOKafkaProducer

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from core.common import tracing, logging_config
from core.common.utils import kafka_json_serializer
from core.config import ConfigManager
from core.providers.key_manager import ApiKeyManager
from core.engine.pattern_loader import load_react_patterns
from core.mcp.server import MCPServerManager
from core.api.services import register_providers
from core.db.mongo import db_manager
from core.tools.native_tools import smart_search_tool, google_search_tool

# Import routers
from core.api.routes import chat, admin, auth, mcp
from core.api.middleware.rate_limit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

logging_config.setup_json_logging()
logger = logging.getLogger("UniversalAIGateway")
# Initialize filters
httpx_logger = logging.getLogger("httpx")
httpx_logger.addFilter(logging_config.ApiKeyFilter())
logger.addFilter(logging_config.ApiKeyFilter())

SUPPORTED_PROVIDERS = [
    "google",
    "google-embedding",
    "google-stt",
    "google-tts",
    "mistral",
    "cerebras",
    "groq",
    "cohere",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages the application lifecycle (startup and shutdown).

    Initializes configuration, logging, database connections, Redis, Kafka,
    and background services. Cleans up resources on shutdown.
    """
    logger.info("Initializing Universal Gateway...")
    app.state.config_manager = ConfigManager()
    app.state.config = app.state.config_manager.get_active_config()
    config = app.state.config
    tracing.setup_tracing()
    FastAPIInstrumentor.instrument_app(app)
    # HTTPXClientInstrumentor().instrument() # Disabled to prevent redundant/leaking logs

    logger.info("Creating a shared httpx.AsyncClient...")
    app.state.http_client = httpx.AsyncClient(timeout=60.0)

    app.state.key_manager = ApiKeyManager(SUPPORTED_PROVIDERS)
    await app.state.key_manager.load_all_keys()
    await app.state.key_manager.start_background_tasks()

    # Inject KeyManager into Global Native Tools
    logger.info("Injecting KeyManager into native tools...")
    google_search_tool.set_key_manager(app.state.key_manager)
    smart_search_tool.set_key_manager(app.state.key_manager)

    # Initialize MongoDB
    try:
        db_manager.connect()
    except Exception as e:
        logger.warning(f"Could not connect to MongoDB: {e}. Auth features may be disabled.")

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_config = app.state.config.get("cache_settings", {})
    if redis_config and redis_config.get("enabled", False):
        try:
            app.state.redis_client = redis.Redis(
                host=redis_host, port=redis_port, db=0, decode_responses=True
            )
            await app.state.redis_client.ping()
            logger.info(
                f"✅ Successfully connected to Redis: {redis_host}:{redis_port}"
            )
        except Exception as e:
            logger.error(
                f"❌ Could not connect to Redis at {redis_host}:{redis_port}: {e}. Caching and SSE will be disabled."
            )
            app.state.redis_client = None
    else:
        logger.warning("Redis is not configured. Caching and SSE will be disabled.")
        app.state.redis_client = None
    load_react_patterns()
    agent_settings = app.state.config.get("agent_settings", {})
    if agent_settings:
        try:
            kafka_broker_url = os.getenv("KAFKA_BROKER", "localhost:29092")
            app.state.kafka_producer = AIOKafkaProducer(
                bootstrap_servers=kafka_broker_url,
                value_serializer=kafka_json_serializer,
            )
            await app.state.kafka_producer.start()
            logger.info("✅ Successfully connected to Kafka (Producer) for ReAct.")
        except Exception as e:
            logger.error(
                f"❌ Could not connect to Kafka Producer: {e}. ReAct API will be unavailable."
            )
            app.state.kafka_producer = None
    else:
        logger.warning(
            "No 'agent_settings' found in config. ReAct features will be disabled."
        )
        app.state.kafka_producer = None

    # Initialize MCP Server Manager (Redis Backed)
    mcp_servers_config = config.get("mcp_servers", [])
    if mcp_servers_config:
        logger.info("Initializing MCPServerManager and awaiting discovery...")
        # Use getattr to safely access http_client, just in case
        shared_http_client = getattr(app.state, "http_client", None)

        app.state.mcp_server_manager = MCPServerManager(
            mcp_servers_config,
            redis_client=app.state.redis_client,
            http_client=shared_http_client
        )

        # Start the file watcher for hot-reloading config
        await app.state.mcp_server_manager.start_watcher()

        # BLOCKING STARTUP: Refresh registry (discover tools) before serving traffic
        try:
            await app.state.mcp_server_manager.refresh_registry()
            logger.info("✅ MCP Discovery Complete.")
        except Exception as e:
            logger.error(f"❌ MCP Discovery Failed during startup: {e}")
            # We don't crash startup, but tools might be unavailable.
    else:
        logger.info("No MCP servers configured.")
        app.state.mcp_server_manager = None

    # Register provider maps
    register_providers()
    logger.info("Application initialized successfully.")
    yield
    logger.info("Shutting down...")

    # Clean up MCPServerManager resources (internal http client if any)
    if hasattr(app.state, "mcp_server_manager") and app.state.mcp_server_manager:
        await app.state.mcp_server_manager.close()

    # No background tasks to stop for MCP manager
    if hasattr(app.state, "kafka_producer") and app.state.kafka_producer:
        await app.state.kafka_producer.stop()

    # Close MongoDB
    db_manager.close()

    if hasattr(app.state, "redis_client") and app.state.redis_client:
        await app.state.redis_client.close()
    if hasattr(app.state, "http_client"):
        logger.info("Closing the shared httpx.AsyncClient...")
        await app.state.http_client.aclose()
    await app.state.key_manager.stop_background_tasks()
    logger.info("Application stopped.")


app = FastAPI(
    title="Universal AI Gateway", version="12.0 (Loki Logging)", lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(mcp.router) # Register new MCP router

# Static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def serve_index():
    return FileResponse("frontend/index.html")
