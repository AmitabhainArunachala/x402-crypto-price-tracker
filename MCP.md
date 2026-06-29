# MCP Server: x402 Crypto Price Tracker

## Overview

Agent-payable crypto market data and revenue intelligence MCP server over HTTP 402/x402. Agents pay per call in USDC on Base — no API keys, no accounts, no subscriptions.

## Tools

| Tool | Description | Price |
|---|---|---|
| `scan_revenue_surfaces` | Rank current agent monetization surfaces with immediate actions | $0.05 |
| `audit_x402_endpoint` | Audit an x402 endpoint for discovery, manifest, paid-route readiness | $0.05 |
| `find_bountybook_jobs` | Find BountyBook jobs likely to pass oracle verification | $0.05 |
| `find_dealwork_low_competition` | Find low-competition DealWork opportunities and bid recommendations | $0.05 |

## Usage

### Browse tools (free)
```bash
curl https://x402.167-172-95-184.nip.io/mcp/tools
```

### Call a tool (paid — $0.05 USDC)
```bash
curl -X POST https://x402.167-172-95-184.nip.io/mcp/call \
  -H "Content-Type: application/json" \
  -d '{"tool":"scan_revenue_surfaces","input":{"focus":"x402"}}'
# Returns HTTP 402 with payment requirements
# Retry with X-PAYMENT header containing EIP-3009 signed payment
```

## Payment Protocol

x402 v2: HTTP 402 → EIP-3009 USDC TransferWithAuthorization → facilitator verify/settle → 200 OK with data.

- Network: Base Sepolia (testnet) / Base Mainnet
- Asset: USDC
- Facilitator: Coinbase (https://x402.org/facilitator)
- Pay-to: 0x68614873C5d624c07DCAA3aFF5243DD5027c3910

## Proven Revenue

5 settled x402 payments ($1.04 total) on Base Sepolia. On-chain transaction hashes verified on BaseScan.