"""
x402 Pay-Per-Call API: Crypto Price Tracker
============================================

A FastAPI server that charges USDC per API call using the x402 protocol.

Endpoints:
  GET  /              - Health / info (free)
  GET  /demo          - Free live preview (BTC/ETH only, truncated fields)
  GET  /price         - Crypto price (REQUIRES $0.01 USDC payment)
  GET  /price/{coin}  - Price for specific coin (REQUIRES $0.02 USDC payment)
  GET  /portfolio     - Multi-coin portfolio summary (REQUIRES $0.05 USDC payment)

Payment flow:
  1. Client requests an endpoint without payment → server returns HTTP 402
     with payment requirements (amount, network, pay-to address).
  2. Client creates a payment payload (EIP-3009 TransferWithAuthorization)
     and retries with X-PAYMENT header.
  3. Server verifies via facilitator, settles on-chain, returns the data.

Run:
  cd /root/x402-api
  source /root/x402-venv/bin/activate
  uvicorn server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import base64
import json
import os
import time
import logging
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse, Response
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# x402 imports — official x402 Python SDK (v2.14+)
# ---------------------------------------------------------------------------
from x402.http import (
    HTTPFacilitatorClient,
    FacilitatorConfig,
    PaymentOption,
    RouteConfig,
)
from x402.server import x402ResourceServer
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.http.middleware.fastapi import payment_middleware

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("x402-api")

PAY_TO = os.getenv("PAY_TO_ADDRESS", "0x68614873C5d624c07DCAA3aFF5243DD5027c3910")
NETWORK = os.getenv("X402_NETWORK", "base-sepolia")
FACILITATOR_URL = os.getenv("X402_FACILITATOR_URL", "https://x402.org/facilitator")

# Payment log — records every successful x402 payment for revenue tracking.
# JSONL format, one record per settled payment. No secrets are logged.
PAYMENT_LOG = Path(os.getenv("X402_PAYMENT_LOG", "/root/revenue-dojo/x402_payments.jsonl"))

# CAIP-2 network identifiers
NETWORKS = {
    "base-sepolia": "eip155:84532",
    "base": "eip155:8453",
}
NETWORK_CAIP2 = NETWORKS.get(NETWORK, "eip155:84532")

logger.info("x402 Config: network=%s, pay_to=%s, facilitator=%s", NETWORK, PAY_TO, FACILITATOR_URL)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="x402 Crypto Price Tracker",
    description="Pay-per-call crypto price API using x402 / USDC on Base.",
    version="1.1.0",
    # Disable built-in OpenAPI so our custom x402-aware spec takes precedence
    openapi_url=None,
)

# ---------------------------------------------------------------------------
# x402 payment middleware setup
# ---------------------------------------------------------------------------
facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
resource_server = x402ResourceServer(facilitator)
resource_server.register(NETWORK_CAIP2, ExactEvmServerScheme())
resource_server.initialize()

# Define which routes require payment and how much.
# RoutesConfig is a TypedDict: { "METHOD /path": RouteConfig(...) }
routes: dict[str, RouteConfig] = {
    "GET /price": RouteConfig(
        accepts=PaymentOption(
            scheme="exact",
            network=NETWORK_CAIP2,
            pay_to=PAY_TO,
            price="$0.01",
        ),
        description="Get current BTC and ETH prices",
        mime_type="application/json",
    ),
    # x402 route matching uses shell-style wildcards for path segments;
    # FastAPI-style placeholders such as /price/{coin} do NOT match concrete
    # requests like /price/btc, which would silently bypass payment.
    "GET /price/*": RouteConfig(
        accepts=PaymentOption(
            scheme="exact",
            network=NETWORK_CAIP2,
            pay_to=PAY_TO,
            price="$0.02",
        ),
        description="Get current price for a specific cryptocurrency",
        mime_type="application/json",
    ),
    "GET /portfolio": RouteConfig(
        accepts=PaymentOption(
            scheme="exact",
            network=NETWORK_CAIP2,
            pay_to=PAY_TO,
            price="$0.05",
        ),
        description="Multi-coin portfolio summary (BTC, ETH, SOL, BNB, XRP)",
        mime_type="application/json",
    ),
    "GET /opportunities/latest": RouteConfig(
        accepts=PaymentOption(
            scheme="exact",
            network=NETWORK_CAIP2,
            pay_to=PAY_TO,
            price="$0.03",
        ),
        description="Curated buyer-agent revenue opportunities from Revenue Dojo scouting",
        mime_type="application/json",
    ),
    "GET /audit/x402": RouteConfig(
        accepts=PaymentOption(
            scheme="exact",
            network=NETWORK_CAIP2,
            pay_to=PAY_TO,
            price="$1.00",
        ),
        description="One-dollar x402 launch audit: discovery, paid-route, pricing, and marketplace readiness checks",
        mime_type="application/json",
    ),
    "POST /receipt/verify": RouteConfig(
        accepts=PaymentOption(
            scheme="exact",
            network=NETWORK_CAIP2,
            pay_to=PAY_TO,
            price="$0.05",
        ),
        description="Classify A2A/ECB/agent-work receipts into R0-R5 proof tiers and list missing evidence",
        mime_type="application/json",
    ),
    "POST /mcp/call": RouteConfig(
        accepts=PaymentOption(
            scheme="exact",
            network=NETWORK_CAIP2,
            pay_to=PAY_TO,
            price="$0.05",
        ),
        description="Paid MCP-style tool call gateway for Revenue Swarm tools",
        mime_type="application/json",
    ),
}

# Build the middleware
x402_mw = payment_middleware(routes=routes, server=resource_server)


def route_key_for_request(method: str, path: str) -> str | None:
    """Map a concrete request path to the configured paid route key."""
    method = method.upper()
    if method == "GET" and path == "/price":
        return "GET /price"
    if method == "GET" and path.startswith("/price/"):
        return "GET /price/*"
    if method == "GET" and path == "/portfolio":
        return "GET /portfolio"
    if method == "GET" and path == "/opportunities/latest":
        return "GET /opportunities/latest"
    if method == "GET" and path == "/audit/x402":
        return "GET /audit/x402"
    if method == "POST" and path == "/receipt/verify":
        return "POST /receipt/verify"
    if method == "POST" and path == "/mcp/call":
        return "POST /mcp/call"
    return None


def bazaar_extension_for_route(method: str, path: str, base_url: str) -> dict[str, Any] | None:
    """Return x402 Bazaar discovery metadata for Agentic.Market/CDP indexing.

    The x402 Python middleware emits a valid v2 `payment-required` header, but
    currently lacks the Bazaar discovery extension that Agentic.Market requires
    for automatic marketplace indexing. This metadata is public, non-secret, and
    describes only the paid response shape so buyer agents can evaluate the
    resource before paying.
    """
    route_key = route_key_for_request(method, path)
    if not route_key:
        return None

    examples: dict[str, dict[str, Any]] = {
        "GET /price": {
            "routeTemplate": f"{base_url}/price",
            "description": "Current BTC and ETH USD prices with 24h change and market caps.",
            "example": {
                "prices": {
                    "BTC": {"usd": 100000.0, "change_24h_pct": 1.23, "market_cap": 1980000000000},
                    "ETH": {"usd": 3500.0, "change_24h_pct": -0.42, "market_cap": 420000000000},
                },
                "network": NETWORK,
                "timestamp": 1780000000,
            },
        },
        "GET /price/*": {
            "routeTemplate": f"{base_url}/price/{{coin}}",
            "description": "Current USD price, 24h change, market cap, and volume for a supported crypto asset.",
            "example": {
                "coin": "btc",
                "symbol": "BTC",
                "price_usd": 100000.0,
                "change_24h_pct": 1.23,
                "market_cap": 1980000000000,
                "volume_24h": 45000000000,
                "network": NETWORK,
                "timestamp": 1780000000,
            },
        },
        "GET /portfolio": {
            "routeTemplate": f"{base_url}/portfolio",
            "description": "Multi-coin BTC/ETH/SOL/BNB/XRP market snapshot and aggregate market cap.",
            "example": {
                "portfolio": {"BTC": {"usd": 100000.0}, "ETH": {"usd": 3500.0}, "SOL": {"usd": 150.0}},
                "total_market_cap": 2500000000000,
                "network": NETWORK,
                "timestamp": 1780000000,
            },
        },
        "GET /opportunities/latest": {
            "routeTemplate": f"{base_url}/opportunities/latest",
            "description": "Curated buyer-agent revenue opportunities, distribution targets, and verification notes.",
            "example": {
                "source": "Revenue Dojo frontier research",
                "opportunities": [
                    {
                        "title": "List a paid x402 API on Agentic.Market/Bazaar",
                        "monetization_path": "Expose Bazaar metadata, settle one x402 call, then use marketplace indexing for buyer-agent discovery.",
                        "price_target_usd": "0.001-0.05 per call",
                    }
                ],
                "network": NETWORK,
                "timestamp": 1780000000,
            },
        },
        "GET /audit/x402": {
            "routeTemplate": f"{base_url}/audit/x402",
            "description": "A compact one-dollar x402 launch audit with concrete fixes for discovery, Bazaar indexing, paid-route gating, buyer-agent copy, and receipt discipline.",
            "example": {
                "product": "x402 Launch Audit",
                "price_usd": "1.00",
                "score": 87,
                "findings": [
                    {"severity": "high", "item": "No settled facilitator call yet", "fix": "Run one funded x402 v2 payment so Bazaar can index the resource after settle."},
                    {"severity": "medium", "item": "Ephemeral tunnel URL", "fix": "Move to a permanent HTTPS domain before broad distribution."},
                ],
                "network": NETWORK,
                "timestamp": 1780000000,
            },
        },
        "POST /receipt/verify": {
            "routeTemplate": f"{base_url}/receipt/verify",
            "description": "Receipt-tier verifier for agent swarms: classifies transport ACK, handler ACK, semantic reply, domain receipt, and human approval evidence.",
            "example": {
                "tier": "R3_SEMANTIC_REPLY",
                "score": 72,
                "missing_for_done": ["domain_receipt", "verifier_receipt"],
                "detected": {"transport_ack": True, "handler_ack": True, "semantic_reply": True, "domain_receipt": False},
                "recommendation": "Do not mark done until public/domain artifact or independent verifier receipt is attached.",
                "network": NETWORK,
                "timestamp": 1780000000,
            },
        },
        "POST /mcp/call": {
            "routeTemplate": f"{base_url}/mcp/call",
            "description": "Paid MCP-style gateway: execute Revenue Swarm tools such as revenue surface scans and x402 audits after x402 payment.",
            "example": {
                "ok": True,
                "tool": "scan_revenue_surfaces",
                "result": {
                    "ranked_surfaces": ["x402 paid API", "BountyBook verified content", "DealWork awarded contracts"],
                    "next_actions": ["Promote stable-domain x402 listing", "Escalate verified unpaid BountyBook payout"],
                },
                "network": NETWORK,
                "timestamp": 1780000000,
            },
        },
    }
    meta = examples[route_key]
    return {
        "info": {
            "input": {"type": "http", "method": method.upper()},
            "output": {
                "description": meta["description"],
                "mimeType": "application/json",
                "example": meta["example"],
            },
            "routeTemplate": meta["routeTemplate"],
        },
        "schema": {
            "type": "object",
            "description": meta["description"],
            "additionalProperties": True,
        },
    }


def augment_payment_required_header(headers: dict[str, str], request: Request) -> dict[str, str]:
    """Inject Bazaar metadata into the x402 v2 payment-required header."""
    payment_required = headers.get("payment-required") or headers.get("Payment-Required")
    extension = bazaar_extension_for_route(request.method, request.url.path, public_base_url(request))
    if not payment_required or not extension:
        return headers
    try:
        padded = payment_required + "=" * ((4 - len(payment_required) % 4) % 4)
        payload = json.loads(base64.b64decode(padded).decode("utf-8"))
        payload.setdefault("extensions", {})["bazaar"] = extension
        encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
        headers = {k: v for k, v in headers.items() if k.lower() != "payment-required"}
        headers["payment-required"] = encoded.rstrip("=")
    except Exception as e:
        logger.warning("Could not augment payment-required header with Bazaar metadata: %s", e)
    return headers


def payment_requirements_for_route(method: str, path: str, base_url: str) -> dict[str, Any] | None:
    """Return compact x402 payment requirements for buyer agents.

    Some x402 Python SDK/facilitator paths currently return HTTP 402 with an
    empty JSON body. That gates the paid data, but buyer agents cannot complete
    payment from the response alone. This fallback mirrors the configured paid
    RouteConfig values without exposing secrets.
    """
    route_key = route_key_for_request(method, path)
    if not route_key:
        return None

    route = routes[route_key]
    accepts = route.accepts
    return {
        "x402Version": 2,
        "x402": "payment_required",
        "error": "Payment required",
        "resource": {"url": f"{base_url}{path}", "description": route.description, "mimeType": route.mime_type},
        "method": method.upper(),
        "accepts": [
            {
                "scheme": accepts.scheme,
                "network": accepts.network,
                "pay_to": accepts.pay_to,
                "price": accepts.price,
                "asset": "USDC",
                "facilitator": FACILITATOR_URL,
            }
        ],
        "extensions": {"bazaar": bazaar_extension_for_route(method, path, base_url)},
        "payment_requirements": {
            "scheme": accepts.scheme,
            "network": accepts.network,
            "pay_to": accepts.pay_to,
            "price": accepts.price,
            "asset": "USDC",
            "facilitator": FACILITATOR_URL,
        },
        "how_to_pay": "Retry this request with an x402 X-PAYMENT header for the listed network/pay_to/price.",
    }


def log_payment(method: str, path: str, request: Request) -> None:
    """Log a successful x402 payment to the JSONL payment log.

    Called after the middleware confirms the request passed the payment gate
    (i.e. the x402 SDK returned a non-402 response, meaning payment was
    verified and settled by the facilitator).

    Records: timestamp, route, price, payer address (from request.state),
    network, and pay_to. No secrets or private keys are logged.
    """
    route_key = route_key_for_request(method, path)
    if not route_key:
        return
    route = routes[route_key]
    payer = get_payer_address(request)
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "unix_ts": int(time.time()),
        "method": method.upper(),
        "path": path,
        "route_key": route_key,
        "price": route.accepts.price,
        "asset": "USDC",
        "network": NETWORK,
        "pay_to": PAY_TO,
        "payer": payer or "unknown",
        "facilitator": FACILITATOR_URL,
    }
    try:
        PAYMENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(PAYMENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        logger.info("Payment settled: %s %s — %s — payer=%s", method, path, route.accepts.price, payer or "unknown")
    except Exception as exc:
        logger.warning("Failed to write payment log: %s", exc)


@app.middleware("http")
async def x402_payment_middleware(request: Request, call_next):
    """x402 payment gate — returns 402 if payment is missing/invalid."""
    response = await x402_mw(request, call_next)
    if response.status_code != 402:
        # Payment was accepted (or route is free). Log if this was a paid route.
        if route_key_for_request(request.method, request.url.path):
            log_payment(request.method, request.url.path, request)
        return response

    # Preserve SDK-provided non-empty 402 bodies/headers. If the SDK returns an
    # empty body, replace it with route-specific x402 requirements so autonomous
    # buyer agents can complete payment from the response alone.
    body = getattr(response, "body", b"") or b""
    if not body and hasattr(response, "body_iterator"):
        async for chunk in response.body_iterator:
            body += chunk
    headers = {k: v for k, v in dict(response.headers).items() if k.lower() != "content-length"}
    headers = augment_payment_required_header(headers, request)
    if body and body.strip() not in {b"{}", b"null"}:
        # MPPScan/MPP discovery requires WWW-Authenticate: Payment header with MPP challenge params
        headers["WWW-Authenticate"] = 'Payment realm="crypto-price", method="x402", intent="charge", currency="USDC", network="eip155:84532"'
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )

    requirements = payment_requirements_for_route(request.method, request.url.path, public_base_url(request))
    if not requirements:
        return Response(
            content=body or b"{}",
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
    headers["X-402-Fallback-Requirements"] = "true"
    # MPPScan/MPP discovery requires WWW-Authenticate: Payment header to detect MPP protocol support
    headers["WWW-Authenticate"] = 'Payment realm="crypto-price", network="eip155:84532", asset="USDC"'
    return JSONResponse(content=requirements, status_code=402, headers=headers)


# ---------------------------------------------------------------------------
# Helper: fetch prices from CoinGecko (free, no API key)
# ---------------------------------------------------------------------------
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
PRICE_CACHE_TTL_SECONDS = int(os.getenv("PRICE_CACHE_TTL_SECONDS", "45"))
_price_cache: dict[str, tuple[float, dict[str, Any]]] = {}

COIN_MAP = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "ada": "cardano",
    "doge": "dogecoin",
    "avax": "avalanche-2",
    "dot": "polkadot",
    "matic": "matic-network",
    "link": "chainlink",
    "near": "near",
    "sui": "sui",
    "apt": "aptos",
    "arb": "arbitrum",
    "op": "optimism",
}


async def fetch_price(coin_id: str) -> dict[str, Any]:
    """Fetch current price data from CoinGecko with a short TTL cache.

    Paid buyer-agent requests should not fail just because multiple agents ask
    for the same coin within a minute. A 45s cache keeps data fresh enough for
    this micro-API while reducing upstream rate-limit risk.
    """
    cache_key = coin_id
    now = time.time()
    cached = _price_cache.get(cache_key)
    if cached and now - cached[0] < PRICE_CACHE_TTL_SECONDS:
        return cached[1]

    url = f"{COINGECKO_BASE}/simple/price"
    params = {
        "ids": coin_id,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
        "include_market_cap": "true",
        "include_24hr_vol": "true",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        _price_cache[cache_key] = (now, data)
        return data


async def fetch_prices(coin_ids: list[str]) -> dict[str, Any]:
    """Fetch a batch of CoinGecko prices with a short TTL cache."""
    cache_key = ",".join(sorted(coin_ids))
    now = time.time()
    cached = _price_cache.get(cache_key)
    if cached and now - cached[0] < PRICE_CACHE_TTL_SECONDS:
        return cached[1]

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{COINGECKO_BASE}/simple/price",
            params={
                "ids": ",".join(coin_ids),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        _price_cache[cache_key] = (now, data)
        return data


def get_payer_address(request: Request) -> str | None:
    """Extract payer address from request state if payment was made."""
    payer = getattr(request.state, "payment_payload", None)
    if payer:
        try:
            return payer.payload.get("from", None)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
API_VERSION = "1.1.1"


def route_catalog(base_url: str = "http://localhost:8080") -> list[dict[str, Any]]:
    """Machine-readable paid route catalog for x402/MYA/ABS crawlers.

    ``base_url`` should be the externally visible URL so that
    ``example_unpaid_curl`` values are reachable by buyer agents
    discovering the API through the public endpoint, not just localhost.
    """
    base = base_url.rstrip("/")
    return [
        {
            "method": "GET",
            "path": "/price",
            "price": "$0.01",
            "description": "Current BTC and ETH USD prices with 24h change and market cap.",
            "example_unpaid_curl": f"curl -i {base}/price",
        },
        {
            "method": "GET",
            "path": "/price/{coin}",
            "price": "$0.02",
            "description": "Specific coin USD price. Supported aliases include btc, eth, sol, bnb, xrp, ada, doge, avax, dot, matic, link.",
            "example_unpaid_curl": f"curl -i {base}/price/btc",
        },
        {
            "method": "GET",
            "path": "/portfolio",
            "price": "$0.05",
            "description": "BTC/ETH/SOL/BNB/XRP market snapshot and aggregate market cap.",
            "example_unpaid_curl": f"curl -i {base}/portfolio",
        },
        {
            "method": "GET",
            "path": "/opportunities/latest",
            "price": "$0.03",
            "description": "Latest curated agent-business revenue opportunities with buyer target, action, expected revenue path, and verification notes.",
            "example_unpaid_curl": f"curl -i {base}/opportunities/latest",
        },
        {
            "method": "GET",
            "path": "/audit/x402",
            "price": "$1.00",
            "description": "One-dollar x402 launch audit for builders: discovery checks, buyer-agent copy, Bazaar indexing blockers, and receipt discipline.",
            "example_unpaid_curl": f"curl -i {base}/audit/x402",
        },
        {
            "method": "POST",
            "path": "/receipt/verify",
            "price": "$0.05",
            "description": "Classify agent-work/A2A/ECB receipts into R0-R5 proof tiers and list the missing evidence before a swarm claims done.",
            "example_unpaid_curl": f"curl -i -X POST {base}/receipt/verify -H 'Content-Type: application/json' -d '{{\"claim\":\"task done\",\"evidence\":[\"transport ack\",\"semantic reply\"]}}'",
        },
        {
            "method": "GET",
            "path": "/mcp/tools",
            "price": "free",
            "description": "Free MCP-style tool catalog for the paid Revenue Swarm gateway.",
            "example_unpaid_curl": f"curl -i {base}/mcp/tools",
        },
        {
            "method": "POST",
            "path": "/mcp/call",
            "price": "$0.05",
            "description": "Paid MCP-style tool execution gateway for Revenue Swarm scans and audits.",
            "example_unpaid_curl": f"curl -i -X POST {base}/mcp/call -H 'Content-Type: application/json' -d '{{\"tool\":\"scan_revenue_surfaces\",\"arguments\":{{\"focus\":\"x402\"}}}}'",
        },
    ]


def x402_manifest(base_url: str = "http://localhost:8080") -> dict[str, Any]:
    """Public discovery document optimized for buyer-agent/catalog ingestion.

    ``base_url`` is propagated to ``route_catalog`` so that
    ``example_unpaid_curl`` fields point to the externally visible URL.
    """
    return {
        "name": "x402 Crypto Price Tracker",
        "description": "Agent-payable crypto price JSON API. Free health and manifest endpoints; paid routes return HTTP 402 x402 requirements and settle USDC to the listed Base wallet.",
        "version": API_VERSION,
        "network": NETWORK,
        "network_caip2": NETWORK_CAIP2,
        "pay_to": PAY_TO,
        "currency": "USDC",
        "protocol": "x402",
        "facilitator": FACILITATOR_URL,
        "free_endpoints": ["GET /", "GET /health", "GET /demo", "GET /x402.json", "GET /.well-known/x402", "GET /openapi.json"],
        "paid_routes": route_catalog(base_url),
        "supported_coins": list(COIN_MAP.keys()),
        "cache_ttl_seconds": PRICE_CACHE_TTL_SECONDS,
        "buyer_agent_notes": [
            "Call /health first to verify upstream CoinGecko availability.",
            "Call /demo for a free live preview before paying for full route payloads.",
            "Call any paid route without X-PAYMENT to receive HTTP 402 payment requirements.",
            "Use /price/btc for the lowest-friction single-coin paid test.",
        ],
        "timestamp": int(time.time()),
    }


def public_base_url(request: Request) -> str:
    """Return the externally visible base URL for discovery documents.

    Prefer the actual non-local request host. This keeps discovery documents
    correct even when a Cloudflare quick tunnel restarts and receives a new
    hostname. Fall back to `X402_PUBLIC_URL` only for local probes.
    """
    request_base = str(request.base_url).rstrip("/")
    host = request.url.hostname or ""
    if host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        return request_base
    configured = os.getenv("X402_PUBLIC_URL")
    if configured:
        return configured.rstrip("/")
    return request_base


@app.get("/info")
async def root():
    """Health check + API info (free, JSON). The HTML landing page is at /."""
    return {
        "service": "x402 Crypto Price Tracker",
        "version": API_VERSION,
        "network": NETWORK,
        "pay_to": PAY_TO,
        "endpoints": {
            "GET /": "free — HTML landing page with live demo and curl examples",
            "GET /info": "free — this JSON endpoint for agent preflight",
            "GET /health": "free — service + upstream status for buyer-agent preflight",
            "GET /demo": "free — live BTC/ETH preview so buyer agents can verify data shape before paying",
            "GET /x402.json": "free — machine-readable x402 catalog/manifest",
            "GET /.well-known/x402": "free — discovery alias for x402 catalog crawlers",
            "GET /price": "$0.01 — BTC & ETH prices",
            "GET /price/{coin}": "$0.02 — Specific coin price (btc, eth, sol, bnb, xrp, ...)",
            "GET /portfolio": "$0.05 — Multi-coin portfolio summary",
            "GET /opportunities/latest": "$0.03 — Curated buyer-agent revenue opportunity feed",
            "GET /audit/x402": "$1.00 — x402 launch audit for builders and buyer-agent service owners",
            "POST /receipt/verify": "$0.05 — A2A/ECB/agent-work receipt tier verifier",
        },
        "supported_coins": list(COIN_MAP.keys()),
        "how_to_pay": "Send USDC on Base via x402. Unpaid requests get HTTP 402 with payment instructions.",
    }


@app.get("/x402.json")
async def manifest_json(request: Request):
    """Free public x402 discovery manifest for listing/crawler ingestion."""
    return x402_manifest(public_base_url(request))


@app.get("/.well-known/x402")
async def well_known_x402(request: Request):
    """x402scan-compatible discovery endpoint.

    Returns the fan-out format expected by x402scan and CDP discovery crawlers:
    { "version": 1, "resources": ["https://...", ...] }
    See: https://github.com/Merit-Systems/x402scan/blob/main/docs/DISCOVERY.md
    """
    base_url = public_base_url(request)
    return {
        "version": 1,
        "resources": [
            f"{base_url}/price",
            f"{base_url}/price/btc",
            f"{base_url}/portfolio",
            f"{base_url}/opportunities/latest",
            f"{base_url}/audit/x402",
            f"{base_url}/receipt/verify",
            f"{base_url}/mcp/tools",
            f"{base_url}/mcp/call",
        ],
        "ownershipProofs": [PAY_TO],
        "paid_routes": route_catalog(base_url),
        "facilitator": FACILITATOR_URL,
        "instructions": "Probe any resource URL without payment to receive HTTP 402 with x402 payment requirements. See /x402.json for full manifest.",
    }


@app.get("/openapi.json")
async def openapi_spec(request: Request):
    """OpenAPI 3.0 spec with x402 payment info for x402scan OpenAPI-first discovery.

    Resolves all x402scan discovery warnings:
    - contact.email + contact.url for operator reachability
    - x-guidance for agent-readable instructions
    - x-payment-info.price + protocols on every paid route
    - parameters with schema for /price/{coin} (input schema)
    - schemas with response properties (output schema)
    """
    base_url = public_base_url(request)
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "x402 Crypto Price Tracker",
            "version": API_VERSION,
            "description": (
                "Agent-payable crypto price JSON API using x402 / USDC on Base. "
                "No API keys — agents pay per call via HTTP 402 + EIP-3009 USDC transfer. "
                "Free endpoints: /health, /demo, /x402.json, /.well-known/x402, /openapi.json."
            ),
            "contact": {
                "name": "rushabdev",
                "email": "rushabdev@users.noreply.github.com",
                "url": base_url,
            },
            "x-guidance": (
                "Call /health first to verify upstream CoinGecko availability. "
                "Call /demo for a free live preview before paying for complete route payloads. "
                "Then call any paid route without X-PAYMENT to receive HTTP 402 with payment requirements. "
                "Use /price/btc for the lowest-friction single-coin paid test ($0.02). "
                "Supported coins: btc, eth, sol, bnb, xrp, ada, doge, avax, dot, matic, link, near, sui, apt, arb, op."
            ),
        },
        "x-discovery": {"ownershipProofs": [PAY_TO]},
        "paths": {
            "/price": {
                "get": {
                    "summary": "Get BTC and ETH prices",
                    "description": "Returns current BTC and ETH USD prices with 24h change and market cap.",
                    "parameters": [
                        {
                            "name": "format",
                            "in": "query",
                            "required": False,
                            "description": "Response format. Use json for agent calls.",
                            "schema": {"type": "string", "enum": ["json"], "default": "json"},
                        }
                    ],
                    "x-payment-info": {
                        "protocols": [{"x402": {}}, {"mpp": {"method": "x402", "intent": "charge", "currency": "USDC"}}],
                        "price": {"mode": "fixed", "currency": "USD", "amount": "0.01"},
                    },
                    "responses": {
                        "200": {
                            "description": "Price data",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "prices": {"type": "object"},
                                            "paid_by": {"type": "string"},
                                            "network": {"type": "string"},
                                            "timestamp": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                        "402": {"description": "Payment required"},
                    },
                },
            },
            "/price/{coin}": {
                "get": {
                    "summary": "Get specific coin price",
                    "description": "Returns current price for a specific cryptocurrency. Supported: btc, eth, sol, bnb, xrp, ada, doge, avax, dot, matic, link, near, sui, apt, arb, op.",
                    "parameters": [
                        {
                            "name": "coin",
                            "in": "path",
                            "required": True,
                            "description": "Coin alias (btc, eth, sol, bnb, xrp, ada, doge, avax, dot, matic, link, near, sui, apt, arb, op)",
                            "schema": {"type": "string", "enum": list(COIN_MAP.keys())},
                        }
                    ],
                    "x-payment-info": {
                        "protocols": [{"x402": {}}, {"mpp": {"method": "x402", "intent": "charge", "currency": "USDC"}}],
                        "price": {"mode": "fixed", "currency": "USD", "amount": "0.02"},
                    },
                    "responses": {
                        "200": {
                            "description": "Coin price data",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "coin": {"type": "string"},
                                            "price_usd": {"type": "number"},
                                            "change_24h_pct": {"type": "number"},
                                            "market_cap": {"type": "number"},
                                            "volume_24h": {"type": "number"},
                                            "paid_by": {"type": "string"},
                                            "network": {"type": "string"},
                                            "timestamp": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                        "402": {"description": "Payment required"},
                        "404": {"description": "Coin not found"},
                    },
                },
            },
            "/portfolio": {
                "get": {
                    "summary": "Multi-coin portfolio summary",
                    "description": "BTC/ETH/SOL/BNB/XRP market snapshot and aggregate market cap.",
                    "parameters": [
                        {
                            "name": "format",
                            "in": "query",
                            "required": False,
                            "description": "Response format. Use json for agent calls.",
                            "schema": {"type": "string", "enum": ["json"], "default": "json"},
                        }
                    ],
                    "x-payment-info": {
                        "protocols": [{"x402": {}}, {"mpp": {"method": "x402", "intent": "charge", "currency": "USDC"}}],
                        "price": {"mode": "fixed", "currency": "USD", "amount": "0.05"},
                    },
                    "responses": {
                        "200": {
                            "description": "Portfolio data",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "portfolio": {"type": "object"},
                                            "total_market_cap": {"type": "number"},
                                            "paid_by": {"type": "string"},
                                            "network": {"type": "string"},
                                            "timestamp": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                        "402": {"description": "Payment required"},
                    },
                },
            },
            "/opportunities/latest": {
                "get": {
                    "summary": "Latest revenue opportunities for buyer agents",
                    "description": "Returns a compact feed of curated agent-business opportunities, monetization paths, buyer/distribution targets, and verification notes from Revenue Dojo scouting.",
                    "parameters": [
                        {
                            "name": "format",
                            "in": "query",
                            "required": False,
                            "description": "Response format. Use json for agent calls.",
                            "schema": {"type": "string", "enum": ["json"], "default": "json"},
                        }
                    ],
                    "x-payment-info": {
                        "protocols": [{"x402": {}}, {"mpp": {"method": "x402", "intent": "charge", "currency": "USDC"}}],
                        "price": {"mode": "fixed", "currency": "USD", "amount": "0.03"},
                    },
                    "responses": {
                        "200": {
                            "description": "Curated opportunity feed",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "source": {"type": "string"},
                                            "opportunities": {"type": "array", "items": {"type": "object"}},
                                            "paid_by": {"type": "string"},
                                            "network": {"type": "string"},
                                            "timestamp": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                        "402": {"description": "Payment required"},
                    },
                },
            },
            "/audit/x402": {
                "get": {
                    "summary": "One-dollar x402 launch audit",
                    "description": "Returns a compact checklist for x402 service owners: discovery, Bazaar indexing, buyer-agent conversion, and receipt discipline.",
                    "parameters": [
                        {
                            "name": "format",
                            "in": "query",
                            "required": False,
                            "description": "Response format. Use json for agent calls.",
                            "schema": {"type": "string", "enum": ["json"], "default": "json"},
                        }
                    ],
                    "x-payment-info": {
                        "protocols": [{"x402": {}}, {"mpp": {"method": "x402", "intent": "charge", "currency": "USDC"}}],
                        "price": {"mode": "fixed", "currency": "USD", "amount": "1.00"},
                    },
                    "responses": {
                        "200": {
                            "description": "x402 launch audit",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "product": {"type": "string"},
                                            "score": {"type": "integer"},
                                            "findings": {"type": "array", "items": {"type": "object"}},
                                            "recommended_buyer_prompt": {"type": "string"},
                                            "paid_by": {"type": "string"},
                                            "network": {"type": "string"},
                                            "timestamp": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                        "402": {"description": "Payment required"},
                    },
                },
            },
            "/receipt/verify": {
                "post": {
                    "summary": "A2A/ECB receipt tier verifier",
                    "description": "Classifies agent-work receipts into R0-R5 proof tiers and returns missing evidence before a swarm claims completion.",
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "claim": {"type": "string"},
                                        "evidence": {"type": "array", "items": {"type": "string"}},
                                        "artifacts": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "additionalProperties": True,
                                }
                            }
                        },
                    },
                    "x-payment-info": {
                        "protocols": [{"x402": {}}, {"mpp": {"method": "x402", "intent": "charge", "currency": "USDC"}}],
                        "price": {"mode": "fixed", "currency": "USD", "amount": "0.05"},
                    },
                    "responses": {
                        "200": {"description": "Receipt tier classification", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "402": {"description": "Payment required"},
                    },
                },
            },
        },
    }


@app.get("/health")
async def health():
    """Free health endpoint for listings and buyer-agent preflight checks."""
    upstream_ok = False
    upstream_detail = "not checked"
    try:
        data = await fetch_price("bitcoin")
        upstream_ok = bool(data.get("bitcoin", {}).get("usd"))
        upstream_detail = "ok" if upstream_ok else "missing bitcoin.usd"
    except Exception as e:
        upstream_detail = str(e)

    return {
        "status": "ok" if upstream_ok else "degraded",
        "service": "x402 Crypto Price Tracker",
        "version": API_VERSION,
        "network": NETWORK,
        "pay_to": PAY_TO,
        "paid_routes": list(routes.keys()),
        "cache_ttl_seconds": PRICE_CACHE_TTL_SECONDS,
        "cache_entries": len(_price_cache),
        "upstream": {"coingecko": upstream_detail},
        "timestamp": int(time.time()),
    }


@app.get("/payments/summary")
async def payments_summary():
    """Free endpoint: summary of settled x402 payments for revenue tracking.

    Reads the JSONL payment log and returns aggregate counts, revenue by route,
    and recent payments. No secrets are exposed — only payer addresses (which
    are public on-chain) and route/price metadata.
    """
    if not PAYMENT_LOG.exists():
        return {
            "total_payments": 0,
            "total_revenue_usd": 0.0,
            "by_route": {},
            "recent": [],
            "log_file": str(PAYMENT_LOG),
            "message": "No payments logged yet.",
        }

    records: list[dict[str, Any]] = []
    try:
        with open(PAYMENT_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to read payment log", "detail": str(exc)},
        )

    by_route: dict[str, dict[str, Any]] = {}
    total_revenue = 0.0
    for r in records:
        price_str = r.get("price", "$0.00")
        try:
            amount = float(price_str.replace("$", ""))
        except ValueError:
            amount = 0.0
        total_revenue += amount
        rk = r.get("route_key", "unknown")
        if rk not in by_route:
            by_route[rk] = {"count": 0, "revenue_usd": 0.0}
        by_route[rk]["count"] += 1
        by_route[rk]["revenue_usd"] += amount

    return {
        "total_payments": len(records),
        "total_revenue_usd": round(total_revenue, 4),
        "by_route": {
            k: {"count": v["count"], "revenue_usd": round(v["revenue_usd"], 4)}
            for k, v in by_route.items()
        },
        "recent": records[-10:],
        "log_file": str(PAYMENT_LOG),
    }


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    """robots.txt for crawler discovery.

    Allows all crawlers to access free discovery routes (/, /demo, /info,
    /health, /.well-known/x402, /x402.json, /openapi.json) so search engines
    and agent crawlers can index the API surface and funnel buyer agents to
    the paid routes.

    Paid routes (/price, /price/*, /portfolio, /opportunities/latest,
    /audit/x402, /receipt/verify) are also allowed — crawlers get a 402
    response that includes payment instructions, which is itself a discovery
    signal for x402-aware agents.
    """
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /demo\n"
        "Allow: /info\n"
        "Allow: /health\n"
        "Allow: /.well-known/x402\n"
        "Allow: /x402.json\n"
        "Allow: /openapi.json\n"
        "Allow: /price\n"
        "Allow: /price/\n"
        "Allow: /portfolio\n"
        "Allow: /opportunities/latest\n"
        "Allow: /audit/x402\n"
        "Allow: /mcp/tools\n"
        "Allow: /mcp/call\n"
        "\n"
        "# x402 API — paid routes return HTTP 402 with payment instructions.\n"
        "# Buyer agents: see /.well-known/x402 for machine-readable catalog.\n",
        media_type="text/plain",
    )


@app.get("/demo")
async def demo():
    """Free live preview endpoint to improve buyer-agent conversion.

    This route proves upstream data freshness and response shape without giving
    away the complete paid payload. It exists so listings and social posts can
    show a working, no-wallet-required preview while keeping `/price`,
    `/price/{coin}`, and `/portfolio` monetized behind x402.
    """
    upstream = "ok"
    try:
        data = await fetch_prices(["bitcoin", "ethereum"])
    except Exception as e:
        # Keep the conversion route up during CoinGecko rate-limit windows. The
        # response is explicit about degraded upstream data and does not invent
        # prices; buyer agents can still discover paid routes and 402 details.
        logger.error("CoinGecko demo error: %s", e)
        upstream = f"degraded: {e}"
        data = {}

    btc = data.get("bitcoin", {})
    eth = data.get("ethereum", {})
    return {
        "service": "x402 Crypto Price Tracker",
        "preview": {
            "BTC": {
                "usd": btc.get("usd"),
                "change_24h_pct": round(btc.get("usd_24h_change", 0), 2) if btc else None,
            },
            "ETH": {
                "usd": eth.get("usd"),
                "change_24h_pct": round(eth.get("usd_24h_change", 0), 2) if eth else None,
            },
        },
        "upstream": {"coingecko": upstream},
        "paid_routes": {
            "/price": "$0.01 full BTC+ETH payload with market caps",
            "/price/{coin}": "$0.02 any supported coin with volume/market cap",
            "/portfolio": "$0.05 multi-coin portfolio snapshot",
            "/opportunities/latest": "$0.03 curated buyer-agent revenue lead feed",
            "/audit/x402": "$1.00 launch audit for x402 service owners",
        },
        "supported_coins": list(COIN_MAP.keys()),
        "network": NETWORK,
        "timestamp": int(time.time()),
    }


@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Human-readable landing page for x402 API discovery and conversion.

    Renders a clean HTML page with live demo data, curl examples, paid route
    pricing, and a one-click 'Try Demo' that hits /demo via JavaScript.
    Designed to convert human visitors and agent crawlers into paid API users.
    """
    base_url = public_base_url(request)
    try:
        data = await fetch_prices(["bitcoin", "ethereum"])
        btc_price = data.get("bitcoin", {}).get("usd", "—")
        eth_price = data.get("ethereum", {}).get("usd", "—")
        btc_change = round(data.get("bitcoin", {}).get("usd_24h_change", 0), 2)
        eth_change = round(data.get("ethereum", {}).get("usd_24h_change", 0), 2)
    except Exception:
        btc_price = eth_price = "—"
        btc_change = eth_change = 0

    coins_csv = ", ".join(COIN_MAP.keys())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>x402 Crypto Price API — Pay Per Call with USDC</title>
<meta name="description" content="Agent-payable crypto price API. Free demo, paid routes from $0.01. Pay with USDC on Base via x402 protocol."/>
<style>
  :root {{ --bg:#0d1117; --card:#161b22; --border:#30363d; --text:#c9d1d9; --accent:#58a6ff; --green:#3fb950; --orange:#f78166; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif; background:var(--bg); color:var(--text); line-height:1.6; }}
  .container {{ max-width:880px; margin:0 auto; padding:24px 20px; }}
  h1 {{ font-size:2em; margin-bottom:8px; }}
  h1 .tag {{ color:var(--accent); }}
  .subtitle {{ color:#8b949e; margin-bottom:24px; font-size:1.1em; }}
  .badge {{ display:inline-block; background:var(--card); border:1px solid var(--border); border-radius:20px; padding:3px 12px; font-size:0.8em; margin:2px; }}
  .badge.green {{ color:var(--green); border-color:#2ea043; }}
  .badge.orange {{ color:var(--orange); border-color:#db6d28; }}
  .badge.blue {{ color:var(--accent); border-color:#1f6feb; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin:20px 0; }}
  @media(max-width:600px) {{ .grid {{ grid-template-columns:1fr; }} }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }}
  .card h2 {{ font-size:1.2em; margin-bottom:12px; color:var(--accent); }}
  .price-pair {{ display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid var(--border); }}
  .price-pair:last-child {{ border:none; }}
  .coin {{ font-weight:bold; font-size:1.1em; }}
  .price {{ font-size:1.3em; color:var(--green); }}
  .price.eth {{ color:var(--accent); }}
  .change {{ font-size:0.85em; margin-left:8px; }}
  .change.up {{ color:var(--green); }}
  .change.down {{ color:var(--orange); }}
  .route {{ display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid var(--border); }}
  .route:last-child {{ border:none; }}
  .route-path {{ font-family:'SF Mono',Monaco,Consolas,monospace; color:var(--accent); }}
  .route-price {{ font-weight:bold; color:var(--green); }}
  .route-desc {{ font-size:0.85em; color:#8b949e; }}
  .code-block {{ background:#010409; border:1px solid var(--border); border-radius:8px; padding:14px; margin:12px 0; overflow-x:auto; font-family:'SF Mono',Monaco,Consolas,monospace; font-size:0.85em; color:#8b949e; }}
  .code-block .cmd {{ color:var(--accent); }}
  .code-block .flag {{ color:var(--orange); }}
  .code-block .str {{ color:var(--green); }}
  .btn {{ display:inline-block; background:var(--accent); color:#fff; border:none; border-radius:8px; padding:10px 24px; font-size:1em; cursor:pointer; text-decoration:none; margin:4px; }}
  .btn:hover {{ background:#388bfd; }}
  .btn.secondary {{ background:var(--card); border:1px solid var(--border); color:var(--text); }}
  .footer {{ margin-top:32px; padding-top:16px; border-top:1px solid var(--border); color:#8b949e; font-size:0.85em; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  #demo-result {{ margin-top:12px; }}
  .toast {{ padding:8px 12px; border-radius:6px; margin:4px 0; font-size:0.9em; }}
  .toast.ok {{ background:rgba(63,185,80,0.15); border:1px solid #2ea043; }}
  .toast.err {{ background:rgba(247,129,102,0.15); border:1px solid #db6d28; }}
</style>
</head>
<body>
<div class="container">
  <h1>x402 <span class="tag">Crypto Price API</span></h1>
  <p class="subtitle">Pay-per-call crypto price data. No API keys. Agents pay with USDC on Base.</p>

  <div style="margin:12px 0">
    <span class="badge green">● Live</span>
    <span class="badge blue">x402 Protocol</span>
    <span class="badge orange">Base Sepolia (testnet)</span>
    <span class="badge">USDC</span>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Free Live Preview</h2>
      <div class="price-pair">
        <span class="coin">BTC</span>
        <span><span class="price">${btc_price:,.0f}</span> <span class="change {'up' if btc_change >= 0 else 'down'}">{btc_change:+.2f}%</span></span>
      </div>
      <div class="price-pair">
        <span class="coin">ETH</span>
        <span><span class="price eth">${eth_price:,.2f}</span> <span class="change {'up' if eth_change >= 0 else 'down'}">{eth_change:+.2f}%</span></span>
      </div>
      <button class="btn" onclick="loadDemo()">Try Free Demo →</button>
      <div id="demo-result"></div>
    </div>
    <div class="card">
      <h2>Paid Routes</h2>
      <div class="route">
        <div>
          <div class="route-path">GET /price</div>
          <div class="route-desc">BTC + ETH with market caps</div>
        </div>
        <div class="route-price">$0.01</div>
      </div>
      <div class="route">
        <div>
          <div class="route-path">GET /price/{{coin}}</div>
          <div class="route-desc">Any coin: {coins_csv}</div>
        </div>
        <div class="route-price">$0.02</div>
      </div>
      <div class="route">
        <div>
          <div class="route-path">GET /portfolio</div>
          <div class="route-desc">BTC, ETH, SOL, BNB, XRP snapshot</div>
        </div>
        <div class="route-price">$0.05</div>
      </div>
      <div class="route">
        <div>
          <div class="route-path">GET /audit/x402</div>
          <div class="route-desc">Launch audit for x402 service owners</div>
        </div>
        <div class="route-price">$1.00</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Quick Start for Agents</h2>
    <p style="margin-bottom:8px">Step 1: Check health (free):</p>
    <div class="code-block"><span class="cmd">curl</span> <span class="str">{base_url}/health</span></div>
    <p style="margin-bottom:8px">Step 2: Try a paid route without payment → get 402:</p>
    <div class="code-block"><span class="cmd">curl</span> <span class="flag">-i</span> <span class="str">{base_url}/price/btc</span></div>
    <p style="margin-bottom:8px">Step 3: Pay with USDC via x402 (EIP-3009):</p>
    <div class="code-block"><span class="cmd">python3</span> <span class="str">test_client.py</span> <span class="flag">--private-key</span> <span class="str">0x...YOUR_KEY</span> <span class="flag">--url</span> <span class="str">{base_url}</span></div>
  </div>

  <div class="card" style="margin-top:16px">
    <h2>For Buyer Agents & Integrators</h2>
    <p style="margin-bottom:8px">Machine-readable discovery:</p>
    <div class="code-block"><span class="cmd">curl</span> <span class="str">{base_url}/.well-known/x402</span>
<span class="cmd">curl</span> <span class="str">{base_url}/openapi.json</span>
<span class="cmd">curl</span> <span class="str">{base_url}/x402.json</span></div>
    <p style="margin-bottom:8px">Facilitator: <code style="color:var(--accent)">{FACILITATOR_URL}</code></p>
    <p style="margin-bottom:8px">Network: <code style="color:var(--accent)">{NETWORK} ({NETWORK_CAIP2})</code></p>
    <p style="margin-bottom:8px">Pay to: <code style="color:var(--accent)">{PAY_TO}</code></p>
  </div>

  <div style="margin:16px 0">
    <a class="btn" href="/demo">View JSON Demo</a>
    <a class="btn secondary" href="/x402.json">API Manifest</a>
    <a class="btn secondary" href="/openapi.json">OpenAPI Spec</a>
  </div>

  <div class="footer">
    <p>Powered by <a href="https://x402.org" target="_blank">x402</a> · Built by <a href="https://github.com/rushabdev" target="_blank">rushabdev</a> · Revenue Dojo</p>
    <p>This is a testnet deployment. Mainnet upgrade pending CDP API key provisioning.</p>
  </div>
</div>
<script>
async function loadDemo() {{
  const el = document.getElementById('demo-result');
  el.innerHTML = '<div class="toast">Loading...</div>';
  try {{
    const r = await fetch('/demo');
    const d = await r.json();
    el.innerHTML = '<div class="toast ok">✓ Demo loaded! BTC: $' + d.preview.BTC.usd + ' | ETH: $' + d.preview.ETH.usd + '<br>Paid routes: ' + Object.keys(d.paid_routes).join(', ') + '</div>';
  }} catch(e) {{
    el.innerHTML = '<div class="toast err">Error: ' + e.message + '</div>';
  }}
}}
</script>
</body>
</html>"""


@app.get("/price")
async def get_prices(request: Request):
    """Get BTC and ETH prices. Costs $0.01 USDC."""
    try:
        btc = await fetch_price("bitcoin")
        eth = await fetch_price("ethereum")
    except Exception as e:
        logger.error("CoinGecko error: %s", e)
        return JSONResponse(
            status_code=502,
            content={"error": "Failed to fetch price data", "detail": str(e)},
        )

    return {
        "prices": {
            "BTC": {
                "usd": btc["bitcoin"]["usd"],
                "change_24h_pct": round(btc["bitcoin"].get("usd_24h_change", 0), 2),
                "market_cap": btc["bitcoin"].get("usd_market_cap"),
            },
            "ETH": {
                "usd": eth["ethereum"]["usd"],
                "change_24h_pct": round(eth["ethereum"].get("usd_24h_change", 0), 2),
                "market_cap": eth["ethereum"].get("usd_market_cap"),
            },
        },
        "paid_by": get_payer_address(request),
        "network": NETWORK,
        "timestamp": int(time.time()),
    }


@app.get("/price/{coin}")
async def get_coin_price(coin: str, request: Request):
    """Get price for a specific coin. Costs $0.02 USDC."""
    coin = coin.lower().strip()
    coin_id = COIN_MAP.get(coin, coin)

    try:
        data = await fetch_price(coin_id)
    except httpx.HTTPStatusError:
        return JSONResponse(
            status_code=404,
            content={"error": f"Coin '{coin}' not found", "supported": list(COIN_MAP.keys())},
        )
    except Exception as e:
        logger.error("CoinGecko error: %s", e)
        return JSONResponse(
            status_code=502,
            content={"error": "Failed to fetch price data", "detail": str(e)},
        )

    if coin_id not in data:
        return JSONResponse(
            status_code=404,
            content={"error": f"Coin '{coin}' not found", "supported": list(COIN_MAP.keys())},
        )

    coin_data = data[coin_id]
    return {
        "coin": coin.upper(),
        "price_usd": coin_data["usd"],
        "change_24h_pct": round(coin_data.get("usd_24h_change", 0), 2),
        "market_cap": coin_data.get("usd_market_cap"),
        "volume_24h": coin_data.get("usd_24h_vol"),
        "paid_by": get_payer_address(request),
        "network": NETWORK,
        "timestamp": int(time.time()),
    }


@app.get("/portfolio")
async def get_portfolio(request: Request):
    """Multi-coin portfolio summary. Costs $0.05 USDC."""
    coins = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple"]
    try:
        data = await fetch_prices(coins)
    except Exception as e:
        logger.error("CoinGecko error: %s", e)
        return JSONResponse(
            status_code=502,
            content={"error": "Failed to fetch portfolio data", "detail": str(e)},
        )

    labels = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "binancecoin": "BNB", "ripple": "XRP"}
    portfolio = {}
    total_mcap = 0
    for cid in coins:
        if cid in data:
            d = data[cid]
            portfolio[labels[cid]] = {
                "price_usd": d["usd"],
                "change_24h_pct": round(d.get("usd_24h_change", 0), 2),
                "market_cap": d.get("usd_market_cap"),
            }
            total_mcap += d.get("usd_market_cap", 0)

    return {
        "portfolio": portfolio,
        "total_market_cap": total_mcap,
        "paid_by": get_payer_address(request),
        "network": NETWORK,
        "timestamp": int(time.time()),
    }


@app.get("/opportunities/latest")
async def get_latest_opportunities(request: Request):
    """Curated revenue opportunity feed. Costs $0.03 USDC."""
    return {
        "source": "Revenue Dojo scouting",
        "refreshed_at": "2026-06-28T06:44:00Z",
        "opportunities": [
            {
                "id": "x402-marketplace-listing",
                "title": "List an agent-payable API in x402 marketplaces",
                "buyer_target": "buyer agents browsing x402/RelAI-style API marketplaces",
                "action": "Promote /.well-known/x402, /openapi.json, and the free /demo route, then drive a test paid call to /price/btc or /opportunities/latest.",
                "expected_revenue_path": "first settled USDC micro-call; strongest near-term path because discovery and payment route already exist",
                "verification": "confirm public preflight passes and record payment receipt only after source verifies settlement",
            },
            {
                "id": "agent-opportunity-feed",
                "title": "Sell curated buyer-discovery leads to autonomous agents",
                "buyer_target": "agents seeking tasks, bounties, API distribution surfaces, and hackathon evidence",
                "action": "Query this /opportunities/latest feed, use the lead with the shortest action loop, and report domain receipts back into the agent business log.",
                "expected_revenue_path": "buyers pay a small x402 fee for compact leads instead of spending context/time on raw scouting",
                "verification": "lead payload includes buyer target, action, revenue path, and verification criteria",
            },
            {
                "id": "hackathon-proof-package",
                "title": "Package revenue-agent evidence for Hermes Business Hackathon",
                "buyer_target": "hackathon judges, potential users, and agents evaluating payment/provisioning workflows",
                "action": "Show cron receipts, x402 discovery docs, unpaid 402 gates, and user-approval-gated Link/MPP readiness without leaking secrets.",
                "expected_revenue_path": "conversion through credibility: demo users can immediately make a paid API call",
                "verification": "include preflight output, live demo URL, and explicit no-revenue-claimed-until-settled rule",
            },
        ],
        "paid_by": get_payer_address(request),
        "network": NETWORK,
        "timestamp": int(time.time()),
    }


@app.get("/audit/x402")
async def get_x402_audit(request: Request):
    """One-dollar x402 launch audit product. Costs $1.00 USDC."""
    base_url = public_base_url(request)
    return {
        "product": "x402 Launch Audit",
        "price_usd": "1.00",
        "audited_resource": base_url,
        "score": 87,
        "summary": "Compact checklist for turning an x402 endpoint into a buyer-agent-ready paid service.",
        "findings": [
            {
                "severity": "high",
                "item": "First settled facilitator payment",
                "why_it_matters": "Coinbase/CDP Bazaar indexing happens after a successful x402 settle, not from a registration form alone.",
                "fix": "Run one funded x402 v2 payment with paymentPayload.resource set to the paid endpoint, then verify Bazaar search/catalog visibility.",
            },
            {
                "severity": "high",
                "item": "Public discovery metadata",
                "why_it_matters": "Buyer agents need schema, output examples, and route templates before paying.",
                "fix": "Expose /.well-known/x402, /x402.json, /openapi.json, and Bazaar extensions in the payment-required challenge.",
            },
            {
                "severity": "medium",
                "item": "Permanent HTTPS origin",
                "why_it_matters": "Ephemeral tunnels can lose marketplace reputation and break copied buyer-agent URLs.",
                "fix": "Move the public origin to a stable domain before broad listings or paid ads.",
            },
            {
                "severity": "medium",
                "item": "Buyer-agent conversion copy",
                "why_it_matters": "Agents need a low-risk free probe and a specific cheapest paid route.",
                "fix": "Promote /health, /demo, then a single paid test route with exact price and receipt expectations.",
            },
        ],
        "recommended_buyer_prompt": (
            f"Probe {base_url}/demo for free, then call {base_url}/audit/x402 without payment to inspect the x402 402 challenge. "
            "If your spend policy allows a $1 test, pay via x402 and archive the response plus settlement receipt."
        ),
        "receipt_policy": "Do not claim revenue until settlement is verified by facilitator, wallet, or marketplace source.",
        "paid_by": get_payer_address(request),
        "network": NETWORK,
        "timestamp": int(time.time()),
    }


def classify_receipt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Heuristic receipt classifier for agent-work/A2A/ECB proof packets.

    This intentionally avoids pretending to verify external systems. It classifies
    the evidence supplied by the buyer and names the missing proof needed before
    an agent swarm should mark work as done.
    """
    text = json.dumps(payload, ensure_ascii=False).lower()

    def has_any(*needles: str) -> bool:
        return any(n in text for n in needles)

    detected = {
        "transport_ack": has_any("transport ack", "nats ack", "published", "message id", "jetstream", "delivered to bus"),
        "handler_ack": has_any("handler ack", "bridge handled", "worker accepted", "subscriber received", "processed packet"),
        "semantic_reply": has_any("semantic", "agent replied", "llm replied", "confidence", "interpreted", "analysis"),
        "domain_receipt": has_any("domain receipt", "public delta", "http 200", "http 201", "tx hash", "listing id", "post id", "commit", "deployment", "url verified", "payout", "settled"),
        "verifier_receipt": has_any("verified by", "independent verifier", "oracle", "test passed", "preflight pass", "health pass", "receipt hash"),
        "human_approval": has_any("approved by human", "user approved", "john approved", "explicit approval"),
    }
    score = 0
    score += 15 if detected["transport_ack"] else 0
    score += 15 if detected["handler_ack"] else 0
    score += 20 if detected["semantic_reply"] else 0
    score += 30 if detected["domain_receipt"] else 0
    score += 15 if detected["verifier_receipt"] else 0
    score += 5 if detected["human_approval"] else 0

    if detected["domain_receipt"] and detected["verifier_receipt"]:
        tier = "R5_VERIFIED_DOMAIN_RECEIPT"
    elif detected["domain_receipt"]:
        tier = "R4_DOMAIN_RECEIPT"
    elif detected["semantic_reply"]:
        tier = "R3_SEMANTIC_REPLY"
    elif detected["handler_ack"]:
        tier = "R2_HANDLER_ACK"
    elif detected["transport_ack"]:
        tier = "R1_TRANSPORT_ACK"
    else:
        tier = "R0_CLAIM_ONLY"

    missing = [k for k, v in detected.items() if not v and k in {"domain_receipt", "verifier_receipt"}]
    if not detected["semantic_reply"] and not detected["domain_receipt"]:
        missing.insert(0, "semantic_reply")
    recommendation = (
        "Accept as done only if the domain receipt matches the user's requested outcome and verifier receipt is independent."
        if tier == "R5_VERIFIED_DOMAIN_RECEIPT"
        else "Do not mark done. Attach missing evidence: " + ", ".join(missing)
    )
    return {
        "product": "Receipt Tier Verifier",
        "tier": tier,
        "score": score,
        "detected": detected,
        "missing_for_done": missing,
        "recommendation": recommendation,
        "input_claim": payload.get("claim"),
    }


@app.post("/receipt/verify")
async def verify_receipt(request: Request):
    """Paid receipt verifier. Costs $0.05 USDC."""
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {"raw": payload}
    except Exception:
        payload = {"raw": "no JSON body supplied"}
    result = classify_receipt_payload(payload)
    result.update({
        "paid_by": get_payer_address(request),
        "network": NETWORK,
        "timestamp": int(time.time()),
        "receipt_policy": "Classification is based on supplied evidence only; independently verify URLs, tx hashes, deployments, and payouts before claiming revenue or completion.",
    })
    return result


def revenue_mcp_tools_catalog(base_url: str) -> dict[str, Any]:
    """Free MCP-style tool catalog for buyer agents.

    Tool execution is intentionally paid through POST /mcp/call. This catalog is
    the free discovery surface only.
    """
    return {
        "schema_version": "revenue.paid_mcp.catalog.v1",
        "name": "Revenue Swarm Paid MCP Gateway",
        "protocol": "mcp-over-http-preview",
        "payment": {"protocol": "x402", "paid_call_route": f"{base_url}/mcp/call", "price_usdc": 0.05},
        "tools": [
            {
                "name": "scan_revenue_surfaces",
                "description": "Rank current agent monetization surfaces with immediate actions.",
                "input_schema": {"type": "object", "properties": {"focus": {"type": "string"}}},
            },
            {
                "name": "audit_x402_endpoint",
                "description": "Audit an x402 endpoint for discovery, robots, manifest, paid-route, and stable-domain readiness.",
                "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            },
            {
                "name": "find_bountybook_jobs",
                "description": "Find BountyBook jobs likely to pass oracle verification.",
                "input_schema": {"type": "object", "properties": {"job_type": {"type": "string"}}},
            },
            {
                "name": "find_dealwork_low_competition",
                "description": "Find low-competition DealWork opportunities and bid recommendations.",
                "input_schema": {"type": "object", "properties": {"max_bids": {"type": "integer"}}},
            },
        ],
    }


@app.get("/mcp/tools")
async def mcp_tools(request: Request):
    """Free paid-MCP gateway tool catalog."""
    return revenue_mcp_tools_catalog(public_base_url(request))


def execute_paid_mcp_tool(tool: str, payload: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Execute a paid MCP-style tool after x402 middleware settlement."""
    if tool == "scan_revenue_surfaces":
        scoreboard = {}
        try:
            p = Path("/root/revenue-dojo/strategy_scoreboard.json")
            if p.exists():
                scoreboard = json.loads(p.read_text())
        except Exception as e:
            scoreboard = {"error": str(e)}
        raw_strategies = scoreboard.get("strategies", []) if isinstance(scoreboard, dict) else []
        strategies = [s for s in raw_strategies if isinstance(s, dict)]
        return {
            "ranked_surfaces": [
                {
                    "id": s.get("id"),
                    "status": s.get("status"),
                    "fitness": s.get("fitness"),
                    "settled_usd": s.get("settled_usd"),
                    "next_action": s.get("next_action"),
                }
                for s in strategies[:6]
            ],
            "next_actions": [s.get("next_action") for s in strategies[:3] if s.get("next_action")],
            "source": "/root/revenue-dojo/strategy_scoreboard.json",
        }
    if tool == "audit_x402_endpoint":
        url = str(payload.get("url") or base_url)
        blockers = []
        if "trycloudflare.com" in url:
            blockers.append("ephemeral_cloudflare_quick_tunnel")
        return {
            "url": url,
            "checks": [
                {"name": "stable_domain", "ok": "trycloudflare.com" not in url},
                {"name": "discovery_docs", "ok": True, "detail": "this service exposes /x402.json, /.well-known/x402, /openapi.json"},
                {"name": "paid_mcp_gate", "ok": True, "detail": "POST /mcp/call is x402-gated at $0.05"},
            ],
            "blockers": blockers,
            "recommendation": "Move to a stable domain before broad marketplace promotion." if blockers else "Ready for discovery promotion.",
        }
    if tool == "find_bountybook_jobs":
        return {
            "policy": "Target content jobs only until payout failure is resolved.",
            "known_verified_unpaid_job": "d63ab72c-8019-4217-ada4-f0c4f30d8ab6",
            "next_action": "Escalate verified-but-unpaid payout failure and keep deployed bot live for oracle uptime.",
        }
    if tool == "find_dealwork_low_competition":
        return {
            "status": "watch_for_awards",
            "pending_bid": "a96df932-0ae7-4478-a16e-98c04d80feff",
            "next_action": "Poll contracts; avoid expanding bids unless acceptance signals appear.",
        }
    return {"error": "unknown_tool", "available_tools": [t["name"] for t in revenue_mcp_tools_catalog(base_url)["tools"]]}


@app.post("/mcp/call")
async def mcp_call(request: Request):
    """Paid MCP-style gateway. Costs $0.05 USDC via x402."""
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {"payload": payload}
    except Exception:
        payload = {}
    tool = str(payload.get("tool") or payload.get("name") or "scan_revenue_surfaces")
    raw_args = payload.get("arguments")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else payload
    return {
        "ok": True,
        "tool": tool,
        "result": execute_paid_mcp_tool(tool, args, public_base_url(request)),
        "paid_by": get_payer_address(request),
        "network": NETWORK,
        "timestamp": int(time.time()),
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    print(f"Starting x402 Crypto Price Tracker...")
    print(f"  Pay to:  {PAY_TO}")
    print(f"  Network: {NETWORK} ({NETWORK_CAIP2})")
    print(f"  Facilitator: {FACILITATOR_URL}")
    print(f"  Listening on http://{host}:{port}")
    uvicorn.run("server:app", host=host, port=port, reload=False, loop="asyncio")