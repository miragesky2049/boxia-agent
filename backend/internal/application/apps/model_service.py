"""模型服务：解析 model_id 为可用 LLMClient，并提供目录浏览与 admin 管理。"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from internal.application.errors import NotFoundError, ValidationError
from internal.domain.llm.client import LLMClient, OpenAICompatLLMClient
from internal.domain.repository.apps_protocols import ModelRepositoryProtocol
from internal.domain.security.ssrf_guard import validate_outbound_url
from internal.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


class ModelService:
    """模型目录服务：解析 model_id、初始化 LLM 客户端、浏览可用模型、admin CRUD。"""

    # 进程内缓存：(base_url, api_key) -> LLMClient，避免重复建连
    _client_cache: dict[tuple[str, str], LLMClient] = {}

    def __init__(self, repo: ModelRepositoryProtocol):
        """仓储由组合根（web/deps/apps_services.py）构造注入；settings 读取保留在本服务。"""
        self._repo: ModelRepositoryProtocol = repo

    # ========== 运行时解析 ==========
    def list_catalog(self) -> list[dict]:
        """列出所有已启用的模型（供前端下拉选择）。

        返回字段：model_id / display_name / provider_name / capabilities。
        capabilities 统一补 default_temperature / default_max_tokens 兜底，
        前端选中模型后可直接回填 temperature/maxTokens 字段。
        若表为空（开发态），回退到 settings.llm_model_id + llm_temperature/llm_max_tokens。
        """
        rows = self._repo.list_catalog()
        if not rows:
            settings = get_settings()
            return [
                {
                    "model_id": settings.llm_model_id,
                    "display_name": settings.llm_model_id,
                    "provider_name": "settings",
                    "capabilities": {
                        "default_temperature": settings.llm_temperature,
                        "default_max_tokens": settings.llm_max_tokens,
                    },
                }
            ]
        normalized: list[dict] = []
        for row in rows:
            caps = dict(row.get("capabilities") or {})
            settings = get_settings()
            caps.setdefault("default_temperature", settings.llm_temperature)
            caps.setdefault("default_max_tokens", settings.llm_max_tokens)
            normalized.append(
                {
                    "model_id": row["model_id"],
                    "display_name": row.get("display_name") or row["model_id"],
                    "provider_name": row.get("provider_name") or "",
                    "capabilities": caps,
                }
            )
        return normalized

    def get_client(self, model_id: str) -> LLMClient:
        """根据 model_id 解析 provider 并构造 LLMClient。

        若目录为空（开发环境），回退到 settings.llm_*。
        """
        resolved = self._repo.resolve_model(model_id)
        if resolved is None:
            settings = get_settings()
            if model_id != settings.llm_model_id:
                raise NotFoundError(f"模型未配置: {model_id}")
            return self._build_cached_client(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key.get_secret_value(),
                model=settings.llm_model_id,
            )

        api_key = resolved["api_key"]
        if not api_key:
            raise ValidationError(f"模型 {model_id} 未配置 api_key")
        return self._build_cached_client(
            base_url=resolved["base_url"],
            api_key=api_key,
            model=model_id,
        )

    def get_client_for_tenant(self, model_id: str, tenant_id: UUID) -> LLMClient:
        """按租户解析模型：优先租户自带 API key，回退平台。

        阶段一：所有 provider 都是 platform，行为同 get_client。
        阶段二：租户可在 model_provider 中注册自己的 key（owner_type=tenant）。
        """
        resolved = self._repo.resolve_model_for_tenant(model_id, tenant_id)
        if resolved is None:
            return self.get_client(model_id)
        api_key = resolved["api_key"]
        if not api_key:
            raise ValidationError(f"模型 {model_id} 未配置 api_key")
        return self._build_cached_client(
            base_url=resolved["base_url"],
            api_key=api_key,
            model=model_id,
        )

    def _build_cached_client(self, *, base_url: str, api_key: str, model: str) -> LLMClient:
        """按 (base_url, api_key) 缓存 client，模型切换不重建连接池。"""
        cache_key = (base_url, api_key)
        client = self._client_cache.get(cache_key)
        if client is None:
            settings = get_settings()
            client = OpenAICompatLLMClient(
                api_key=api_key,
                model=model,
                base_url=base_url,
                timeout_seconds=settings.llm_timeout_seconds,
                default_temperature=settings.llm_temperature,
                default_max_tokens=settings.llm_max_tokens,
            )
            self._client_cache[cache_key] = client
        return client

    # ========== admin CRUD ==========
    def list_providers(self, owner_type: str | None = None) -> list[dict]:
        return self._repo.list_providers(owner_type)

    def create_provider(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        owner_type: str = "platform",
        owner_id: UUID | None = None,
    ) -> UUID:
        validate_outbound_url(base_url)
        existing = self._repo.list_providers(owner_type)
        if any(p["name"] == name for p in existing):
            raise ValidationError(f"provider 已存在: {name}")
        return self._repo.create_provider(name, base_url, api_key, owner_type, owner_id)

    def update_provider(
        self,
        provider_id: UUID,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        is_enabled: bool | None = None,
    ) -> None:
        if self._repo.get_provider(provider_id) is None:
            raise NotFoundError("provider 不存在")
        if base_url is not None:
            validate_outbound_url(base_url)
        self._repo.update_provider(
            provider_id, base_url=base_url, api_key=api_key, is_enabled=is_enabled
        )
        # 凭据变更后清缓存，下次请求重建 client
        if api_key is not None or base_url is not None:
            self._client_cache.clear()

    def delete_provider(self, provider_id: UUID) -> None:
        if self._repo.get_provider(provider_id) is None:
            raise NotFoundError("provider 不存在")
        self._repo.delete_provider(provider_id)

    def list_catalog_full(self) -> list[dict]:
        """admin 用：列出所有模型（含禁用、含凭据的 provider 名）。"""
        return self._repo.list_catalog_full()

    def create_catalog(
        self,
        *,
        provider_id: UUID,
        model_id: str,
        display_name: str = "",
        capabilities: dict[str, Any] | None = None,
    ) -> UUID:
        if self._repo.get_provider(provider_id) is None:
            raise NotFoundError("provider 不存在")
        return self._repo.create_catalog(provider_id, model_id, display_name, capabilities)

    def update_catalog(
        self,
        catalog_id: UUID,
        *,
        provider_id: UUID | None = None,
        display_name: str | None = None,
        capabilities: dict[str, Any] | None = None,
        is_enabled: bool | None = None,
    ) -> None:
        if self._repo.get_catalog(catalog_id) is None:
            raise NotFoundError("模型不存在")
        if provider_id is not None and self._repo.get_provider(provider_id) is None:
            raise NotFoundError("provider 不存在")
        self._repo.update_catalog(
            catalog_id,
            provider_id=provider_id,
            display_name=display_name,
            capabilities=capabilities,
            is_enabled=is_enabled,
        )

    def delete_catalog(self, catalog_id: UUID) -> None:
        if self._repo.get_catalog(catalog_id) is None:
            raise NotFoundError("模型不存在")
        self._repo.delete_catalog(catalog_id)

    # ========== bootstrap ==========
    def seed_from_settings(self) -> None:
        """启动时把 settings.llm_* 写入 model_provider + model_catalog。

        只在不存在时插入，永不覆盖已有凭证——管理员在 admin 端改的 key 不能被
        每次启动或每次请求的 seed 动作回退。
        """
        settings = get_settings()
        if not settings.llm_api_key.get_secret_value():
            logger.warning("LLM_API_KEY 未配置，跳过模型目录 seed")
            return

        # provider：同名已存在则直接复用，不 UPDATE base_url / api_key
        existing_providers = self._repo.list_providers(owner_type="platform")
        provider_id: UUID | None = next(
            (p["id"] for p in existing_providers if p["name"] == "deepseek"),
            None,
        )
        if provider_id is None:
            provider_id = self._repo.create_provider(
                name="deepseek",
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key.get_secret_value(),
                owner_type="platform",
                owner_id=None,
            )

        # catalog：model_id 已存在则跳过，不覆盖 display_name / capabilities
        existing_catalog = self._repo.list_catalog_full()
        if any(c["model_id"] == settings.llm_model_id for c in existing_catalog):
            return
        self._repo.create_catalog(
            provider_id=provider_id,
            model_id=settings.llm_model_id,
            display_name="DeepSeek Chat",
            capabilities={
                "supports_tools": True,
                "context_window": 64000,
                "max_output_tokens": 4096,
            },
        )
