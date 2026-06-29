"""Probe signatures of key x402 functions."""
import inspect
from x402.http.middleware.fastapi import payment_middleware, payment_middleware_from_config, PaymentMiddlewareASGI
from x402.http import HTTPFacilitatorClient, FacilitatorConfig, PaymentOption, RouteConfig, RoutesConfig
from x402.server import x402ResourceServer
from x402.mechanisms.evm.exact import ExactEvmServerScheme

print("=== payment_middleware signature ===")
print(inspect.signature(payment_middleware))
print("\n=== payment_middleware docstring ===")
print(payment_middleware.__doc__ or "(none)")

print("\n=== payment_middleware_from_config signature ===")
print(inspect.signature(payment_middleware_from_config))
print("\n=== payment_middleware_from_config docstring ===")
print(payment_middleware_from_config.__doc__ or "(none)")

print("\n=== PaymentOption fields ===")
try:
    print(PaymentOption.__dataclass_fields__)
except:
    print(dir(PaymentOption))
    # Try pydantic
    try:
        print("model_fields:", PaymentOption.model_fields)
    except:
        pass

print("\n=== RouteConfig fields ===")
try:
    print(RouteConfig.__dataclass_fields__)
except:
    try:
        print("model_fields:", RouteConfig.model_fields)
    except:
        print(dir(RouteConfig))

print("\n=== RoutesConfig fields ===")
try:
    print(RoutesConfig.__dataclass_fields__)
except:
    try:
        print("model_fields:", RoutesConfig.model_fields)
    except:
        print(dir(RoutesConfig))

print("\n=== PaymentMiddlewareASGI init ===")
try:
    print(inspect.signature(PaymentMiddlewareASGI.__init__))
except:
    print(dir(PaymentMiddlewareASGI))

print("\n=== x402ResourceServer ===")
print(inspect.signature(x402ResourceServer.__init__))

print("\n=== ExactEvmServerScheme ===")
print(inspect.signature(ExactEvmServerScheme.__init__))

print("\n=== HTTPFacilitatorClient ===")
print(inspect.signature(HTTPFacilitatorClient.__init__))

print("\n=== FacilitatorConfig ===")
try:
    print(FacilitatorConfig.__dataclass_fields__)
except:
    try:
        print("model_fields:", FacilitatorConfig.model_fields)
    except:
        print(dir(FacilitatorConfig))

print("\nDONE")