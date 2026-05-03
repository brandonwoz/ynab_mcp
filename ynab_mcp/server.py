import json
import logging
import os

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

load_dotenv()

logging.basicConfig(level=logging.INFO)


# HA add-ons get config via /data/options.json, not environment variables
load_dotenv()


def get_config() -> dict:
    options_path = "/data/options.json"
    if os.path.exists(options_path):
        with open(options_path) as f:
            return json.load(f)
    return {
        "ynab_token": os.environ.get("YNAB_TOKEN", ""),
        "api_key": os.environ.get("API_KEY", ""),
    }


config = get_config()
YNAB_TOKEN = config.get("ynab_token", "")
API_KEY = config.get("api_key", "")

BASE_URL = "https://api.ynab.com/v1"

MILLIUNIT = 1000


mcp = FastMCP("YNAB", host="0.0.0.0", port=8000)


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth check if no API key is configured
        if API_KEY:
            key = request.query_params.get("key", "")
            if key != API_KEY:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


def _headers() -> dict:
    return {"Authorization": f"Bearer {YNAB_TOKEN}"}


@mcp.tool()
async def list_plans() -> list[dict]:
    """
    List all YNAB plans for the user.

    Use this first to get plan IDs before calling any other tools.
    Returns plan names and IDs.
    """
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_URL}/plans", headers=_headers())
        r.raise_for_status()

    plans = r.json()["data"]["plans"]
    return [{"id": p["id"], "name": p["name"]} for p in plans]


@mcp.tool()
async def list_accounts(plan_id: str) -> list:
    """Get a list of accounts from YNAB."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/plans/{plan_id}/accounts", headers=_headers()
        )
        response.raise_for_status()
        accounts = response.json()["data"]["accounts"]
        # Filter out closed/deleted accounts and convert milliunits
    return [
        {
            "name": a["name"],
            "type": a["type"],
            "balance": a["balance"] / MILLIUNIT,
            "cleared_balance": a["cleared_balance"] / MILLIUNIT,
            "uncleared_balance": a["uncleared_balance"] / MILLIUNIT,
            "on_budget": a["on_budget"],
        }
        for a in accounts
        if a["closed"] is False and a["deleted"] is False
    ]


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
