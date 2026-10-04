"""Check that the configured providers and models actually answer (J6).

    cd backend && python -m app.core.provider_check

Makes one minimal request to each configured provider using the exact model
names from settings (env / .env), and prints which ones work. Keys are never
printed. Exit code 1 if a configured provider fails; unconfigured ones are
reported as skipped, since the app runs without them (searches then fail
honestly and screenshots cannot be read).
"""

import asyncio
import sys

import httpx

from app.core.config import settings


async def _check_serpapi(client: httpx.AsyncClient) -> str:
    res = await client.get("https://serpapi.com/account.json", params={"api_key": settings.SERPAPI_API_KEY})
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code}")
    left = res.json().get("total_searches_left")
    return f"ok, {left} searches left this month" if left is not None else "ok"


async def _check_groq(client: httpx.AsyncClient) -> str:
    res = await client.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        json={"model": settings.GROQ_MODEL, "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 5},
    )
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code} for model {settings.GROQ_MODEL}")
    return f"ok, model {settings.GROQ_MODEL} answered"


async def _check_gemini(client: httpx.AsyncClient) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent"
    res = await client.post(
        url,
        headers={"x-goog-api-key": settings.GEMINI_API_KEY},
        json={"contents": [{"parts": [{"text": "Reply with OK."}]}]},
    )
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code} for model {settings.GEMINI_MODEL}")
    return f"ok, model {settings.GEMINI_MODEL} answered"


CHECKS = [
    ("SerpApi (search)", "SERPAPI_API_KEY", _check_serpapi),
    ("Groq (document reading)", "GROQ_API_KEY", _check_groq),
    ("Gemini (document reading fallback)", "GEMINI_API_KEY", _check_gemini),
]


async def main() -> int:
    failed = False
    async with httpx.AsyncClient(timeout=20) as client:
        for label, key_name, check in CHECKS:
            if not getattr(settings, key_name, "").strip():
                print(f"[skip] {label}: {key_name} is not set")
                continue
            try:
                print(f"[ ok ] {label}: {await check(client)}")
            except Exception as exc:
                failed = True
                # Never echo the response body or URL: either may contain the key.
                detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                print(f"[FAIL] {label}: {detail}")
    print(f"Database: {settings.DATABASE_URL.split('://', 1)[0]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
