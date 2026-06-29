"""
x402 Client Test Script
=======================

Tests the x402 Crypto Price Tracker API:
  1. Free endpoint (/)
  2. Paid endpoint without payment → expect HTTP 402
  3. (Optional) Paid endpoint WITH payment → expect HTTP 200

For step 3, you need a funded EVM wallet on Base Sepolia with testnet USDC.
Get testnet funds from: https://docs.cdp.coinbase.com/faucets/introduction/quickstart

Usage:
  # Just test steps 1 & 2 (no wallet needed):
  python test_client.py

  # Full test with payment (requires funded wallet):
  python test_client.py --private-key 0xYOUR_PRIVATE_KEY
"""

import sys
import json
import argparse
import requests

BASE_URL = "http://localhost:8080"


def test_free_endpoint():
    """Step 1: Hit the free root endpoint."""
    print("\n" + "=" * 60)
    print("STEP 1: Free endpoint GET /")
    print("=" * 60)
    resp = requests.get(f"{BASE_URL}/")
    print(f"Status: {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))


def test_unpaid_402():
    """Step 2: Hit a paid endpoint WITHOUT payment → should get 402."""
    print("\n" + "=" * 60)
    print("STEP 2: Paid endpoint GET /price WITHOUT payment (expect 402)")
    print("=" * 60)
    resp = requests.get(f"{BASE_URL}/price")
    print(f"Status: {resp.status_code}")
    if resp.status_code == 402:
        print("✓ Got HTTP 402 Payment Required — x402 middleware is working!")
        # Show payment requirements
        for header in ["X-PAYMENT-REQUIREMENTS", "payment-requirements", "PAYMENT-REQUIRED"]:
            val = resp.headers.get(header)
            if val:
                print(f"\n{header}:")
                try:
                    print(json.dumps(json.loads(val), indent=2))
                except json.JSONDecodeError:
                    print(val[:500])
        # Also try printing response body
        try:
            body = resp.json()
            print("\nResponse body:")
            print(json.dumps(body, indent=2))
        except Exception:
            print(f"\nResponse body: {resp.text[:500]}")
    else:
        print(f"✗ Expected 402, got {resp.status_code}")
        print(resp.text[:500])


def test_paid_request(private_key: str):
    """Step 3: Make a PAID request using the x402 client."""
    print("\n" + "=" * 60)
    print("STEP 3: Paid endpoint GET /price WITH payment")
    print("=" * 60)

    try:
        from x402 import x402ClientSync
        from x402.mechanisms.evm.exact import ExactEvmScheme
        from eth_account import Account
    except ImportError as e:
        print(f"Cannot import x402 client libraries: {e}")
        print("Install with: pip install 'x402[evm,requests]'")
        return

    # Create signer from private key
    account = Account.from_key(private_key)
    print(f"Payer wallet: {account.address}")

    # Set up x402 client
    client = x402ClientSync()
    signer = ExactEvmScheme(signer=account)
    client.register("eip155:*", signer)

    # First request → get 402 with payment requirements
    resp = requests.get(f"{BASE_URL}/price")
    if resp.status_code != 402:
        print(f"Expected 402, got {resp.status_code}. Is the server running?")
        return

    # Parse payment requirements from response
    req_header = resp.headers.get("X-PAYMENT-REQUIREMENTS") or resp.headers.get("payment-requirements")
    if not req_header:
        print("No payment requirements header found in 402 response")
        print("Headers:", dict(resp.headers))
        return

    payment_required = json.loads(req_header)
    print(f"Payment required: {json.dumps(payment_required, indent=2)}")

    # Create payment payload
    try:
        payment_payload = client.create_payment_payload(payment_required)
    except Exception as e:
        print(f"Failed to create payment: {e}")
        return

    # Encode and resend with payment
    payment_header = client.encode_payment_signature_header(payment_payload)

    # The header might be a dict of headers
    headers = {}
    if isinstance(payment_header, dict):
        headers.update(payment_header)
    elif isinstance(payment_header, str):
        headers["X-PAYMENT"] = payment_header
    else:
        headers["X-PAYMENT"] = str(payment_header)

    print(f"Sending payment headers: {list(headers.keys())}")
    resp2 = requests.get(f"{BASE_URL}/price", headers=headers)
    print(f"\nStatus: {resp2.status_code}")

    if resp2.status_code == 200:
        print("✓ Payment accepted! Response:")
        print(json.dumps(resp2.json(), indent=2))
        # Check for settlement header
        settlement = resp2.headers.get("X-PAYMENT-RESPONSE") or resp2.headers.get("payment-response")
        if settlement:
            print(f"\nSettlement: {settlement}")
    else:
        print(f"Payment failed: {resp2.text[:500]}")


def main():
    parser = argparse.ArgumentParser(description="Test x402 Crypto Price API")
    parser.add_argument(
        "--private-key",
        type=str,
        default=None,
        help="EVM private key for making paid requests (hex, 0x-prefixed)",
    )
    parser.add_argument("--url", type=str, default=BASE_URL, help="Base URL of the API")
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = args.url

    # Step 1: Free endpoint
    test_free_endpoint()

    # Step 2: Unpaid → 402
    test_unpaid_402()

    # Step 3: Paid request (optional)
    if args.private_key:
        test_paid_request(args.private_key)
    else:
        print("\n" + "=" * 60)
        print("SKIP STEP 3: No --private-key provided")
        print("=" * 60)
        print("To test full payment flow:")
        print("  1. Get testnet ETH + USDC: https://docs.cdp.coinbase.com/faucets/")
        print("  2. Run: python test_client.py --private-key 0xYOUR_KEY")

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()