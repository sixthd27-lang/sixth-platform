"""
start.py — يشغل البوت والسيرفر في نفس الوقت
تشغيل: python start.py
"""
import asyncio, os, subprocess, sys

def run():
    # تشغيل السيرفر (FastAPI) على PORT
    port = os.getenv("PORT","8000")
    server = subprocess.Popen([
        sys.executable, "-m", "uvicorn",
        "server:app", "--host", "0.0.0.0", "--port", port
    ])
    # تشغيل البوت
    bot = subprocess.Popen([sys.executable, "bot.py"])
    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()
        bot.terminate()

if __name__ == "__main__":
    run()
