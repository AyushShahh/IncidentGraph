"""Realistic HTTP traffic generator sending requests to the API Gateway."""
import argparse
import asyncio
import os
import random
import sys
import time
from typing import Any
import httpx


async def configure_gateway_failure(
    client: httpx.AsyncClient,
    gateway_url: str,
    failure_rate: float,
    trigger_after: int,
) -> None:
    """Configure failure simulation settings on the Gateway before starting traffic."""
    if failure_rate <= 0.0:
        return

    url = f"{gateway_url}/simulate-failure"
    payload = {
        "failure_rate": failure_rate,
        "trigger_after_n_calls": trigger_after,
        "enabled_failures": [
            "database_timeout",
            "network_timeout",
            "http_500",
            "authentication_failure",
            "retry_exhaustion",
        ],
    }
    try:
        resp = await client.post(url, json=payload, timeout=5.0)
        if resp.status_code == 200:
            print(f"[CONFIG] Configured Gateway failure rate={failure_rate}, trigger_after={trigger_after}")
        else:
            print(f"[CONFIG] Warning: Could not configure failure simulation (status {resp.status_code}): {resp.text}")
    except Exception as exc:
        print(f"[CONFIG] Warning: Failed to reach Gateway at {url} to set failure config: {exc}")


async def send_checkout_request(
    client: httpx.AsyncClient,
    gateway_url: str,
    request_num: int,
) -> dict[str, Any]:
    """Execute a single realistic checkout transaction through Gateway."""
    url = f"{gateway_url}/api/checkout"
    skus = ["SKU-100", "SKU-200", "SKU-300"]
    selected_sku = random.choice(skus[:2])  # SKU-100 or SKU-200 usually in stock

    payload = {
        "user_id": f"user-{random.randint(1000, 9999)}",
        "items": [
            {
                "sku": selected_sku,
                "quantity": random.randint(1, 2),
                "unit_price": round(random.uniform(15.0, 85.0), 2),
            }
        ],
        "payment_method": "credit_card",
    }

    start = time.perf_counter()
    status = "ERROR"
    status_code = 0
    err_msg = None

    try:
        resp = await client.post(url, json=payload, timeout=10.0)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        status_code = resp.status_code
        if resp.status_code == 200:
            status = "OK"
        else:
            status = f"HTTP_{resp.status_code}"
            err_msg = resp.text[:100]
    except httpx.TimeoutException:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        status = "TIMEOUT"
        err_msg = "Request timed out"
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        status = "CONN_ERROR"
        err_msg = str(exc)

    return {
        "request_num": request_num,
        "status": status,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "error": err_msg,
    }


async def run_traffic_generator(
    gateway_url: str,
    rate: float,
    duration: float,
    failure_rate: float,
    trigger_after: int,
    burst_size: int,
) -> None:
    """Generate continuous traffic by sending requests to Gateway APIs."""
    print("=" * 60)
    print("AI Incident Intelligence Platform - Realistic Traffic Generator")
    print(f"Target Gateway : {gateway_url}")
    print(f"Rate           : {rate} requests/second")
    print(f"Duration       : {duration} seconds")
    print(f"Failure Rate   : {failure_rate * 100:.1f}% (trigger after {trigger_after} calls)")
    print(f"Burst Size     : {burst_size}")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Pre-configure failure rate if requested
        if failure_rate > 0.0:
            await configure_gateway_failure(client, gateway_url, failure_rate, trigger_after)

        interval = 1.0 / (rate / burst_size) if rate > 0 else 1.0
        start_time = time.time()
        end_time = start_time + duration
        total_requests = 0
        success_count = 0
        fail_count = 0
        latencies: list[float] = []

        while time.time() < end_time:
            tick_start = time.time()

            tasks = [
                send_checkout_request(client, gateway_url, total_requests + i + 1)
                for i in range(burst_size)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                total_requests += 1
                if isinstance(res, dict):
                    latencies.append(res["latency_ms"])
                    if res["status"] == "OK":
                        success_count += 1
                        print(f"[{time.strftime('%H:%M:%S')}] Req #{res['request_num']}: SUCCESS 200 ({res['latency_ms']}ms)")
                    else:
                        fail_count += 1
                        print(f"[{time.strftime('%H:%M:%S')}] Req #{res['request_num']}: FAILURE {res['status']} ({res['latency_ms']}ms) - {res['error']}")
                else:
                    fail_count += 1
                    print(f"[{time.strftime('%H:%M:%S')}] Req #{total_requests}: ERROR: {res}")

            elapsed = time.time() - tick_start
            sleep_time = max(0.0, interval - elapsed)
            if sleep_time > 0 and time.time() < end_time:
                await asyncio.sleep(sleep_time)

        # Print summary
        avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
        print("\n" + "=" * 60)
        print("Traffic Generation Summary")
        print(f"Total Requests  : {total_requests}")
        print(f"Successful (200): {success_count} ({success_count / max(1, total_requests) * 100:.1f}%)")
        print(f"Failures        : {fail_count} ({fail_count / max(1, total_requests) * 100:.1f}%)")
        print(f"Average Latency : {avg_latency:.2f}ms")
        print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Microservices HTTP Traffic Generator")
    parser.add_argument(
        "--gateway-url",
        default=os.getenv("GATEWAY_URL", "http://localhost:8001"),
        help="API Gateway base URL (default: http://localhost:8001)",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=5.0,
        help="Requests per second (default: 5.0)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Test duration in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--failure-rate",
        type=float,
        default=0.0,
        help="Failure rate 0.0 to 1.0 (default: 0.0)",
    )
    parser.add_argument(
        "--trigger-after",
        type=int,
        default=0,
        help="Initial successful calls before failures start (default: 0)",
    )
    parser.add_argument(
        "--burst-size",
        type=int,
        default=1,
        help="Number of concurrent requests per burst (default: 1)",
    )

    args = parser.parse_args()
    asyncio.run(
        run_traffic_generator(
            gateway_url=args.gateway_url,
            rate=args.rate,
            duration=args.duration,
            failure_rate=args.failure_rate,
            trigger_after=args.trigger_after,
            burst_size=args.burst_size,
        )
    )


if __name__ == "__main__":
    main()
