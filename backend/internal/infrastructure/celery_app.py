"""Celery 应用工厂：从 settings 读取 broker/backend，注册异步任务。"""

from __future__ import annotations

from celery import Celery

from internal.infrastructure.config.settings import get_settings


def make_celery() -> Celery:
    """构造 Celery 实例；worker 进程通过 `celery -A internal.infrastructure.celery_app worker` 启动。"""
    settings = get_settings()
    app = Celery(
        "boxia_agent",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=[
            "internal.infrastructure.tasks.ingest_tasks",
            "internal.infrastructure.tasks.auth_tasks",
            "internal.infrastructure.tasks.entitlement_tasks",
            "internal.infrastructure.tasks.entitlement_reconcile",
        ],
    )
    app.conf.update(
        task_default_queue="rag",
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        beat_schedule={
            "auth-process-wait-effective": {
                "task": "auth.process_wait_effective",
                "schedule": 300.0,
            },
            "auth-process-expired": {
                "task": "auth.process_expired",
                "schedule": 300.0,
            },
            "entitlement-scan-expiry-reminders": {
                "task": "entitlement.scan_expiry_reminders",
                "schedule": 86400.0,
            },
            "entitlement-reconcile": {
                "task": "entitlement.reconcile",
                "schedule": 86400.0,
            },
            "entitlement-process-grace-revoked": {
                "task": "entitlement.process_grace_revoked",
                "schedule": 86400.0,
            },
        },
    )
    return app


celery_app = make_celery()
