# x402 Crypto Price Tracker — Revenue Swarm Paid API

> Agent-payable crypto market data and revenue intelligence over HTTP 402 / x402.
> No API keys. Agents pay per call in USDC on Base. Free preview available.

## Live Demo

**Base URL:** https://x402.167-172-95-184.nip.io

### Free Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Landing page with live prices, curl examples, and try button |
| `GET /demo` | Free live preview (BTC/ETH, truncated) |
| `GET /health` | Service health + upstream status |
| `GET /mcp/tools` | Free MCP tool catalog (4 tools) |
| `GET /.well-known/x402` | x402 discovery manifest |
| `GET /x402.json` | Machine-readable service manifest |
| `GET /openapi.json` | OpenAPI 3.0.3 spec with x-payment-info extensions |

### Paid Endpoints (HTTP 402 → USDC payment → 200)

| Endpoint | Price | Description |
|---|---|---|
| `GET /price` | $0.01 | BTC + ETH prices with 24h change and market cap |
| `GET /price/{coin}` | $0.02 | Price for any of 16 supported coins (btc, eth, sol, bnb, xrp, ada, doge, avax, dot, matic, link, near, sui, apt, arb, op) |
| `GET /portfolio` | $0.05 | Multi-coin portfolio snapshot (BTC, ETH, SOL, BNB, XRP) |
| `GET /opportunities/latest` | $0.03 | Curated buyer-agent revenue opportunity feed |
| `GET /audit/x402` | $1.00 | One-dollar x402 launch audit with concrete fixes |
| `POST /receipt/verify` | $0.05 | Classify A2A/ECB/agent-work receipts into R0-R5 proof tiers |
| `POST /mcp/call` | $0.05 | Paid MCP-style tool call gateway (4 revenue tools) |

### MCP Tools

| Tool | Description |
|---|---|
| `scan_revenue_surfaces` | Rank current agent monetization surfaces with immediate actions |
| `audit_x402_endpoint` | Audit an x402 endpoint for discovery, robots, manifest, and paid-route readiness |
| `find_bountybook_jobs` | Find BountyBook jobs likely to pass oracle verification |
| `find_dealwork_low_competition` | Find low-competition DealWork opportunities and bid recommendations |

## Quick Start

```bash
# 1. Try the free demo
curl https://x402.167-172-95-184.nip.io/demo

# 2. Hit a paid endpoint (returns HTTP 402 with payment requirements)
curl -i https://x402.167-172-95-184.nip.io/price/btc

# 3. Browse the MCP tool catalog
curl https://x402.167-172-95-184.nip.io/mcp/tools

# 4. Call a paid MCP tool (returns 402)
curl -X POST https://x402.167-172-95-184.nip.io/mcp/call \
  -H "Content-Type: application/json" \
  -d '{"tool":"scan_revenue_surfaces","input":{"focus":"x402"}}'
```

## Self-Host

```bash
git clone https://github.com/AmitabhainArunachala/x402-crypto-price-tracker.git
cd x402-crypto-price-tracker

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure
export PAY_TO_ADDRESS="0xYourWalletAddress"
export X402_NETWORK="base-sepolia"  # or "base" for mainnet
export X402_PUBLIC_URL="https://your-domain.com"

# Run
uvicorn server:app --host 0.0.0.0 --port 8080
```

## Architecture

- **Framework:** FastAPI + uvicorn
- **Payment protocol:** x402 v2 (HTTP 402 + EIP-3009 USDC TransferWithAuthorization)
- **Facilitator:** Coinbase x402 facilitator (https://x402.org/facilitator)
- **Network:** Base Sepolia (testnet) / Base Mainnet
- **Data source:** CoinGecko free API (no API key needed)
- **Discovery:** Bazaar extension on all 402 responses, `.well-known/x402`, OpenAPI 3.0.3

## Proven Revenue

- **5 settled x402 payments** on Base Sepolia ($1.04 total)
- Payment log: `x402_payments.jsonl` in deployment
- First settled payment: 2026-06-29T14:34:41Z
- Both micro ($0.01) and standard ($1.00) price points proven
- On-chain transaction hashes verified on BaseScan

> Note: Current payments are self-pay proof-of-concept on testnet. The next milestone is a third-party paid call on Base Mainnet.

## Part of Revenue Swarm

This API is one component of the Revenue Swarm — a Hermes Agent business system that:
- Scouts revenue opportunities (DealWork, MYA, BountyBook)
- Exposes paid APIs (x402)
- Coordinates sibling agents (A2A/NATS)
- Requests approval-gated spending (Stripe Link/Projects)
- Records evidence tiers (R0-R5 receipt discipline)

## License

MIT