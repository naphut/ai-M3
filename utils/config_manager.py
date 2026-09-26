import os
import json
from pathlib import Path
from utils.logger import logger

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

def get_gemini_api_key() -> str:
    """
    Get the configured Gemini API key from environment, config.json, or .env file.
    """
    # 1. Environment variable
    env_val = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_val:
        return env_val

    # 2. config.json
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                key = data.get("gemini_api_key", "").strip()
                if key:
                    os.environ["GEMINI_API_KEY"] = key
                    return key
        except Exception as e:
            logger.debug(f"Error reading config.json: {e}")

    # 3. .env file
    if ENV_FILE.exists():
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GEMINI_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if key:
                            os.environ["GEMINI_API_KEY"] = key
                            return key
        except Exception as e:
            logger.debug(f"Error reading .env: {e}")

    return ""

def save_gemini_api_key(key: str) -> bool:
    """
    Save the Gemini API key persistently to config.json and .env, and set in os.environ.
    """
    clean_key = (key or "").strip()
    if not clean_key:
        return False

    os.environ["GEMINI_API_KEY"] = clean_key

    # Save to config.json
    try:
        data = {}
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["gemini_api_key"] = clean_key
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving to config.json: {e}")

    # Save to .env
    try:
        env_lines = []
        found = False
        if ENV_FILE.exists():
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("GEMINI_API_KEY="):
                        env_lines.append(f"GEMINI_API_KEY={clean_key}\n")
                        found = True
                    else:
                        env_lines.append(line)
        if not found:
            env_lines.append(f"GEMINI_API_KEY={clean_key}\n")

        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.writelines(env_lines)
    except Exception as e:
        logger.error(f"Error saving to .env: {e}")

    # Synchronize to ai-audio-translator/.env
    try:
        react_env = BASE_DIR / "ai-audio-translator" / ".env"
        if react_env.parent.exists():
            react_lines = []
            react_found = False
            if react_env.exists():
                with open(react_env, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("GEMINI_API_KEY="):
                            react_lines.append(f"GEMINI_API_KEY={clean_key}\n")
                            react_found = True
                        else:
                            react_lines.append(line)
            if not react_found:
                react_lines.append(f"GEMINI_API_KEY={clean_key}\n")
                react_lines.append("PORT=3000\n")
            with open(react_env, "w", encoding="utf-8") as f:
                f.writelines(react_lines)
    except Exception as e:
        logger.error(f"Error syncing to ai-audio-translator/.env: {e}")

    logger.info("🔑 Gemini API Key saved persistently across Desktop and React Engine!")
    return True

def test_gemini_api_key(key: str) -> tuple:
    """
    Verify if the Gemini API key is valid by sending a lightweight test request.
    Returns (True, "Success message") or (False, "Error message").
    """
    clean_key = (key or "").strip()
    if not clean_key:
        return False, "API Key is empty."

    import requests
    models = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.6-flash"]
    payload = {"contents": [{"parts": [{"text": "Hello"}]}]}
    headers = {"Content-Type": "application/json"}

    last_error = ""
    for model in models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={clean_key}"
            resp = requests.post(url, headers=headers, json=payload, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                if "candidates" in data:
                    return True, f"✅ API Key Valid! Connected to Gemini ({model})."
            else:
                try:
                    err_json = resp.json()
                    err_msg = err_json.get("error", {}).get("message", resp.text)
                    last_error = f"HTTP {resp.status_code}: {err_msg}"
                except Exception:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            last_error = str(e)

    return False, f"❌ Gemini test failed: {last_error}"
