from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)

active_websocket_connections = Gauge(
    "active_websocket_connections",
    "Number of active WebSocket connections",
)

messages_sent_total = Counter(
    "messages_sent_total",
    "Total messages sent",
    ["type"],
)

messages_received_total = Counter(
    "messages_received_total",
    "Total messages received",
    ["type"],
)

rate_limit_hits_total = Counter(
    "rate_limit_hits_total",
    "Total rate limit hits",
    ["endpoint"],
)

db_query_duration_seconds = Histogram(
    "db_query_duration_seconds",
    "Database query latency in seconds",
    ["operation"],
)


async def metrics_endpoint() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)