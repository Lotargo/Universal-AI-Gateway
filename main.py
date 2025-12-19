import uvicorn
from dotenv import load_dotenv

load_dotenv()

from core.api.server import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
