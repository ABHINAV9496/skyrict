"""Integration tests for the text-CAPTCHA challenge (Step 3 of the wizard)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration

_VALID_PASSWORD = "ValidPass123!"
_EMAIL = "captcha-gate@test.com"


class TestCaptcha:
    async def test_issue_returns_image_and_test_answer(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/auth/signup/captcha")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["captchaId"]
        assert data["image"].startswith("data:image/png;base64,")
        assert data["expiresIn"] > 0
        assert data["answer"], "test env must return the plaintext answer"

    async def test_wrong_answer_is_rejected(self, client: AsyncClient) -> None:
        captcha_id, _ = await self._fetch(client)
        resp = await client.post(
            "/api/v1/auth/signup/password",
            json={
                "email": _EMAIL,
                "verificationToken": "bogus-token",
                "password": _VALID_PASSWORD,
                "captchaId": captcha_id,
                "captchaAnswer": "WRONG",
            },
        )
        assert resp.status_code == 422, resp.text

    async def test_correct_answer_is_single_use(self, client: AsyncClient) -> None:
        captcha_id, answer = await self._fetch(client)
        first = await client.post(
            "/api/v1/auth/signup/password",
            json={
                "email": _EMAIL,
                "verificationToken": "bogus-token",
                "password": _VALID_PASSWORD,
                "captchaId": captcha_id,
                "captchaAnswer": answer,
            },
        )
        assert first.status_code == 401, first.text

        replay = await client.post(
            "/api/v1/auth/signup/password",
            json={
                "email": _EMAIL,
                "verificationToken": "bogus-token",
                "password": _VALID_PASSWORD,
                "captchaId": captcha_id,
                "captchaAnswer": answer,
            },
        )
        assert replay.status_code == 422, replay.text

    @staticmethod
    async def _fetch(client: AsyncClient) -> tuple[str, str]:
        resp = await client.get("/api/v1/auth/signup/captcha")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["answer"]
        return data["captchaId"], data["answer"]
