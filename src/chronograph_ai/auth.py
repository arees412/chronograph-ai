"""Deployment-supplied API authorization boundary."""

from __future__ import annotations

from typing import Protocol

from fastapi import Request


class AuthProvider(Protocol):
    async def authorize(self, request: Request) -> None: ...


class AllowAllAuthProvider:
    """Local-only default; production deployments must replace this provider."""

    async def authorize(self, request: Request) -> None:
        del request
