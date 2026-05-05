"""应用入口。"""

import uvicorn

from agent.config import config
from agent.api import app

if __name__ == "__main__":
    config.load()
    uvicorn.run(app, host="0.0.0.0", port=8000)
