"""
Celery application factory, queue definitions, task routing, and beat schedule.
"""

import os

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "sentinel",
    include=[
        "backend.tasks.fetch_tasks",
        "backend.tasks.extraction_tasks",
        "backend.tasks.enrichment_tasks",
        "backend.tasks.pipeline_tasks",
        "backend.tasks.scheduled_tasks",
    ],
)

# ---------------------------------------------------------------------------
# Broker / result backend
# ---------------------------------------------------------------------------
app.conf.broker_url = BROKER_URL
app.conf.result_backend = RESULT_BACKEND

# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
app.conf.accept_content = ["json"]
app.conf.task_serializer = "json"
app.conf.result_serializer = "json"

# ---------------------------------------------------------------------------
# Reliability
# ---------------------------------------------------------------------------
app.conf.task_acks_late = True                 # ACK only after task completes
app.conf.worker_prefetch_multiplier = 1        # One task at a time per process
app.conf.task_reject_on_worker_lost = True     # Re-queue on crash
app.conf.broker_connection_retry_on_startup = True

# ---------------------------------------------------------------------------
# Queue topology
# ---------------------------------------------------------------------------
default_exchange = Exchange("default", type="direct")
extraction_exchange = Exchange("extraction", type="direct")
fetch_exchange = Exchange("fetch", type="direct")
enrichment_exchange = Exchange("enrichment", type="direct")

app.conf.task_queues = (
    Queue("default", default_exchange, routing_key="default"),
    Queue("extraction", extraction_exchange, routing_key="extraction"),
    Queue("fetch", fetch_exchange, routing_key="fetch"),
    Queue("enrichment", enrichment_exchange, routing_key="enrichment"),
)

app.conf.task_default_queue = "default"
app.conf.task_default_exchange = "default"
app.conf.task_default_routing_key = "default"

# ---------------------------------------------------------------------------
# Task routing
# ---------------------------------------------------------------------------
app.conf.task_routes = {
    "backend.tasks.fetch_tasks.run_fetch": {"queue": "fetch"},
    "backend.tasks.extraction_tasks.run_process": {"queue": "extraction"},
    "backend.tasks.extraction_tasks.run_batch_extract": {"queue": "extraction"},
    "backend.tasks.enrichment_tasks.run_batch_enrich": {"queue": "enrichment"},
    "backend.tasks.enrichment_tasks.run_enrichment": {"queue": "enrichment"},
    "backend.tasks.pipeline_tasks.run_full_pipeline": {"queue": "default"},
    "backend.tasks.scheduled_tasks.scheduled_fetch": {"queue": "fetch"},
    "backend.tasks.scheduled_tasks.cleanup_stale_jobs": {"queue": "default"},
    "backend.tasks.scheduled_tasks.aggregate_metrics": {"queue": "default"},
    "backend.tasks.scheduled_tasks.refresh_materialized_views": {"queue": "default"},
}

# ---------------------------------------------------------------------------
# Beat schedule (periodic tasks)
# ---------------------------------------------------------------------------
app.conf.beat_schedule = {
    "fetch-rss-hourly": {
        "task": "backend.tasks.scheduled_tasks.scheduled_fetch",
        "schedule": crontab(minute=0),  # Every hour at :00
    },
    "cleanup-stale-jobs": {
        "task": "backend.tasks.scheduled_tasks.cleanup_stale_jobs",
        "schedule": crontab(minute="*/15"),  # Every 15 minutes
    },
    "aggregate-metrics": {
        "task": "backend.tasks.scheduled_tasks.aggregate_metrics",
        "schedule": crontab(minute="*/5"),  # Every 5 minutes
    },
    "refresh-materialized-views": {
        "task": "backend.tasks.scheduled_tasks.refresh_materialized_views",
        "schedule": crontab(minute=30, hour="*/6"),  # Every 6 hours at :30
    },
}

