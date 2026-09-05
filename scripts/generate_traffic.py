"""Realistic Production Traffic Simulator for AI Incident Intelligence Platform.

Generates realistic end-user checkout traffic and natural edge-case code bugs across microservices.
No artificial failure injection - errors occur naturally through request parameters and edge-case inputs.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import os
import random
import sys
import time
from typing import Any, Optional
import httpx


SCENARIOS = [
    "normal",
    "zero_division",
    "inventory_batch_overflow",
    "currency_lookup_error",
    "customer_tier_error",
    "payment_declines",
    "mixed_incident",
]


def build_request_payload(scenario_type: str, request_num: int) -> dict[str, Any]:
    """Construct realistic checkout payload based on the selected scenario type."""
    user_num = random.randint(1000, 9999)

    if scenario_type == "zero_division":
        # Edge case: Promotional coupon on zero-dollar sample triggers ZeroDivisionError in Gateway
        return {
            "user_id": f"user-std-{user_num}",
            "items": [{"sku": "SKU-PROMO", "quantity": 1, "unit_price": 0.0}],
            "payment_method": "credit_card",
            "currency": "USD",
            "discount_code": "ZERO_SUBTOTAL",
        }

    elif scenario_type == "inventory_batch_overflow":
        # Edge case: Bulk order with 4+ items triggers off-by-one IndexError in Inventory batch slicing
        return {
            "user_id": f"user-std-{user_num}",
            "items": [
                {"sku": "SKU-100", "quantity": 1, "unit_price": 25.0},
                {"sku": "SKU-100", "quantity": 1, "unit_price": 25.0},
                {"sku": "SKU-200", "quantity": 1, "unit_price": 40.0},
                {"sku": "SKU-200", "quantity": 1, "unit_price": 40.0},
            ],
            "payment_method": "credit_card",
            "currency": "USD",
        }

    elif scenario_type == "currency_lookup_error":
        # Edge case: Unsupported currency "GBP" triggers KeyError in Payments exchange rate lookup
        return {
            "user_id": f"user-std-{user_num}",
            "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 35.0}],
            "payment_method": "credit_card",
            "currency": "GBP",
        }

    elif scenario_type == "customer_tier_error":
        # Edge case: Unhandled customer tier "platinum" triggers KeyError in Orders loyalty tier lookup
        return {
            "user_id": f"user-tier-platinum-{user_num}",
            "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 45.0}],
            "payment_method": "credit_card",
            "currency": "USD",
        }

    elif scenario_type == "payment_declines":
        # Natural business decline: Customer's card is declined by issuing bank
        return {
            "user_id": f"user-std-{user_num}",
            "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 60.0}],
            "payment_method": "card_declined",
            "currency": "USD",
        }

    else:
        # Happy path standard checkout
        tier = random.choice(["std", "std", "vip", "gold"])
        user_id = f"user-{tier}-{user_num}" if tier != "std" else f"user-std-{user_num}"
        sku = random.choice(["SKU-100", "SKU-100", "SKU-200"])
        qty = random.randint(1, 2)
        price = round(random.uniform(20.0, 50.0), 2)
        return {
            "user_id": user_id,
            "items": [{"sku": sku, "quantity": qty, "unit_price": price}],
            "payment_method": "credit_card",
            "currency": "USD",
            "discount_code": "SAVE10" if random.random() < 0.2 else None,
        }


async def send_checkout_request(
    client: httpx.AsyncClient,
    gateway_url: str,
    request_num: int,
    scenario_type: str,
) -> dict[str, Any]:
    """Execute a single realistic checkout transaction through Gateway."""
    url = f"{gateway_url}/api/checkout"
    payload = build_request_payload(scenario_type, request_num)

    start = time.perf_counter()
    status = "ERROR"
    status_code = 0
    error_code = None
    err_msg = None

    try:
        resp = await client.post(url, json=payload, timeout=10.0)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        status_code = resp.status_code
        error_code = resp.headers.get("x-error-code")

        if resp.status_code == 200:
            status = "OK"
        else:
            status = f"HTTP_{resp.status_code}"
            try:
                resp_json = resp.json()
                error_code = error_code or resp_json.get("error") or resp_json.get("exception_type")
                err_msg = resp_json.get("detail") or resp_json.get("message") or resp.text[:100]
            except Exception:
                err_msg = resp.text[:100]

    except httpx.TimeoutException:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        status = "TIMEOUT"
        error_code = "CLIENT_TIMEOUT"
        err_msg = "Gateway request timed out after 10.0s"
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        status = "CONN_ERROR"
        error_code = type(exc).__name__
        err_msg = str(exc)

    return {
        "request_num": request_num,
        "scenario": scenario_type,
        "status": status,
        "status_code": status_code,
        "error_code": error_code,
        "latency_ms": latency_ms,
        "error": err_msg,
        "user_id": payload.get("user_id"),
    }


async def run_traffic_simulator(
    gateway_url: str,
    rate: float,
    duration: float,
    scenario: str,
    failure_rate: float,
    warmup: float,
    burst_size: int,
    seed: Optional[int] = None,
) -> None:
    """Continuously generate traffic and simulate realistic production incidents."""
    if seed is not None:
        random.seed(seed)

    print("=" * 70)
    print("AI Incident Intelligence Platform - Production Traffic Simulator")
    print(f"Target Gateway : {gateway_url}")
    print(f"Scenario       : {scenario}")
    print(f"Rate           : {rate} requests/second")
    print(f"Duration       : {duration} seconds (Warm-up: {warmup}s)")
    print(f"Failure Rate   : {failure_rate * 100:.1f}% (during active failure phase)")
    print(f"Burst Size     : {burst_size}")
    if seed is not None:
        print(f"Random Seed    : {seed}")
    print("=" * 70)

    # Edge cases available for mixed incidents
    incident_types = [
        "zero_division",
        "inventory_batch_overflow",
        "currency_lookup_error",
        "customer_tier_error",
        "payment_declines",
    ]

    async with httpx.AsyncClient(timeout=15.0) as client:
        interval = 1.0 / (rate / burst_size) if rate > 0 else 1.0
        start_time = time.time()
        end_time = start_time + duration
        total_requests = 0
        success_count = 0
        fail_count = 0
        latencies: list[float] = []
        error_counts: dict[str, int] = {}

        while time.time() < end_time:
            tick_start = time.time()
            elapsed_total = tick_start - start_time
            in_warmup = elapsed_total < warmup

            tasks = []
            for _ in range(burst_size):
                req_id = total_requests + len(tasks) + 1

                # Select request scenario
                if in_warmup or scenario == "normal":
                    req_scenario = "normal"
                elif scenario in incident_types:
                    req_scenario = scenario if random.random() < failure_rate else "normal"
                elif scenario == "mixed_incident":
                    if random.random() < failure_rate:
                        req_scenario = random.choice(incident_types)
                    else:
                        req_scenario = "normal"
                else:
                    req_scenario = "normal"

                tasks.append(send_checkout_request(client, gateway_url, req_id, req_scenario))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                total_requests += 1
                if isinstance(res, dict):
                    latencies.append(res["latency_ms"])
                    ts = time.strftime("%H:%M:%S")

                    if res["status"] == "OK":
                        success_count += 1
                        print(f"[{ts}] Req #{res['request_num']:04d}: SUCCESS 200 ({res['latency_ms']}ms) | user={res['user_id']}")
                    else:
                        fail_count += 1
                        code = res.get("error_code") or f"HTTP_{res['status_code']}"
                        error_counts[code] = error_counts.get(code, 0) + 1
                        print(f"[{ts}] Req #{res['request_num']:04d}: FAILURE {res['status']} ({res['latency_ms']}ms) | code={code} | {res['error']}")
                else:
                    fail_count += 1
                    error_counts["UNEXPECTED"] = error_counts.get("UNEXPECTED", 0) + 1
                    print(f"[{time.strftime('%H:%M:%S')}] Req #{total_requests:04d}: EXCEPTION: {res}")

            elapsed = time.time() - tick_start
            sleep_time = max(0.0, interval - elapsed)
            if sleep_time > 0 and time.time() < end_time:
                await asyncio.sleep(sleep_time)

        # Print summary
        avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
        success_pct = (success_count / max(1, total_requests)) * 100
        fail_pct = (fail_count / max(1, total_requests)) * 100

        print("\n" + "=" * 70)
        print("Traffic Simulation Summary")
        print(f"Total Requests  : {total_requests}")
        print(f"Successful (200): {success_count} ({success_pct:.1f}%)")
        print(f"Failures        : {fail_count} ({fail_pct:.1f}%)")
        print(f"Average Latency : {avg_latency:.2f}ms")
        if error_counts:
            print("\nError Code Distribution:")
            for code, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {code:28s}: {count:4d} ({count / total_requests * 100:.1f}%)")
        print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Production Traffic Simulator for AI Incident Intelligence Platform",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--gateway-url",
        default=os.getenv("GATEWAY_URL", "http://localhost:8001"),
        help="API Gateway base URL",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=5.0,
        help="Requests per second",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Total test duration in seconds",
    )
    parser.add_argument(
        "--scenario",
        default="mixed_incident",
        choices=SCENARIOS,
        help="Incident scenario to execute",
    )
    parser.add_argument(
        "--failure-rate",
        type=float,
        default=0.15,
        help="Probability of failure-inducing requests (0.0 to 1.0)",
    )
    parser.add_argument(
        "--warmup",
        type=float,
        default=2.0,
        help="Warm-up seconds of pure normal traffic before failures begin",
    )
    parser.add_argument(
        "--burst-size",
        type=int,
        default=1,
        help="Number of concurrent requests per burst",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible traffic distribution",
    )

    args = parser.parse_args()

    # If user selected a specific failure scenario, default failure-rate to 1.0 unless explicitly specified
    failure_rate = args.failure_rate
    if args.scenario in ["zero_division", "inventory_batch_overflow", "currency_lookup_error", "customer_tier_error", "payment_declines"] and args.failure_rate == 0.15:
        failure_rate = 1.0

    asyncio.run(
        run_traffic_simulator(
            gateway_url=args.gateway_url,
            rate=args.rate,
            duration=args.duration,
            scenario=args.scenario,
            failure_rate=failure_rate,
            warmup=args.warmup,
            burst_size=args.burst_size,
            seed=args.seed,
        )
    )


if __name__ == "__main__":
    main()
