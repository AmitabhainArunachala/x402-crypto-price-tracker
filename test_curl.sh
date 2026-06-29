#!/bin/bash
# Quick test for x402 API - no wallet needed
echo "=== Testing free endpoint ==="
curl -s http://localhost:8080/ | python3 -m json.tool 2>/dev/null

echo ""
echo "=== Testing paid endpoint without payment (should get 402) ==="
curl -s -v http://localhost:8080/price 2>&1 | head -20

echo ""
echo "=== Testing specific coin (should get 402 without payment) ==="
curl -s -v http://localhost:8080/price/btc 2>&1 | head -20