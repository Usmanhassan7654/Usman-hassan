"""Start the assistant:  python run.py   then open http://localhost:8000"""

import threading
import webbrowser

import uvicorn

if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()
    uvicorn.run("app.server:app", host="127.0.0.1", port=8000)
