from __future__ import annotations

import httpx
import structlog

from identity.core.config import Environment, settings

logger = structlog.get_logger("identity.turnstile")

_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileVerifier:
    def __init__(
        self,
        *,
        secret_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._secret_key = secret_key if secret_key is not None else settings.TURNSTILE_SECRET_KEY
        self._client = client

    async def verify(self, token: str | None) -> bool:
        if not self._secret_key:
            return settings.ENVIRONMENT in (Environment.DEV, Environment.TEST)
        if not token:
            return False
        try:
            if self._client is not None:
                response = await self._client.post(
                    _TURNSTILE_VERIFY_URL,
                    data={"secret": self._secret_key, "response": token},
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        _TURNSTILE_VERIFY_URL,
                        data={"secret": self._secret_key, "response": token},
                    )
            payload = response.json()
            return bool(payload.get("success"))
        except Exception as exc:
            logger.warning("turnstile_verify_failed", error=str(exc))
            return False
