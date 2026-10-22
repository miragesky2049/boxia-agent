"""应用配置：基于 pydantic-settings 分层加载并校验环境变量。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[3]
INSECURE_SECRETS = {
    "change-me",
    "change-me-in-production",
    "dev-jwt-secret-change-me-0123456789abcdef",
    "dev-secret",
    "secret",
    "test",
}


class Settings(BaseSettings):
    """应用级配置，进程环境变量优先于 .env 文件。"""

    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "boxia-agent"
    app_version: str = "1.0.0"
    platform_name: str = "Agent运营管理平台"

    database_url: str
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout: int = Field(default=10, ge=1, le=120)
    database_pool_recycle: int = Field(default=1800, ge=60)
    statement_timeout_ms: int = Field(default=5000, ge=100)
    lock_timeout_ms: int = Field(default=3000, ge=100)

    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "boxia-agent"
    jwt_audience: str = "boxia-admin"
    access_token_minutes: int = Field(default=30, ge=1, le=120)
    refresh_token_days: int = Field(default=14, ge=1, le=90)

    bcrypt_rounds: int = Field(default=12, ge=4, le=16)
    login_max_attempts: int = Field(default=5, ge=1, le=20)
    login_lock_minutes: int = Field(default=15, ge=1, le=1440)

    # 多租户域名配置：根域名如 example.com，产品级平台固定使用 adminsystem 子域名。
    # 留空时仅通过 X-Tenant-Code（开发/测试）识别租户，未提供则进入产品级平台。
    root_domain: str = ""
    platform_admin_subdomain: str = "adminsystem"
    default_tenant_code: str = ""
    # 是否允许用请求头识别租户；留空时生产环境关闭、其他环境开启。
    allow_tenant_header: bool | None = None

    cors_origins: str = ""
    log_level: str = "INFO"
    log_json: bool | None = None
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "boxia-agent"
    otel_traces_sampler_ratio: float = Field(default=1.0, ge=0.0, le=1.0)

    docs_enabled: bool | None = None
    legacy_api_enabled: bool = True
    user_api_token: SecretStr | None = None

    @property
    def is_production(self) -> bool:
        """是否生产环境。"""
        return self.app_env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        """解析逗号分隔的 CORS 白名单。"""
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def effective_log_json(self) -> bool:
        """日志格式：生产默认 JSON，可用 LOG_JSON 覆盖。"""
        return self.is_production if self.log_json is None else self.log_json

    @property
    def effective_docs_enabled(self) -> bool:
        """API 文档：生产默认关闭。"""
        return not self.is_production if self.docs_enabled is None else self.docs_enabled

    @property
    def tenant_header_enabled(self) -> bool:
        """是否允许 X-Tenant-Code 请求头识别租户。"""
        if self.allow_tenant_header is None:
            return not self.is_production
        return self.allow_tenant_header

    @property
    def normalized_root_domain(self) -> str:
        """规范化根域名（小写、去除首尾点）。"""
        return self.root_domain.strip().lower().strip(".")

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        """生产环境启动硬校验，避免带病上线。"""
        if not self.is_production:
            return self

        secret = self.jwt_secret.get_secret_value()
        if len(secret) < 32 or secret in INSECURE_SECRETS:
            raise ValueError("生产环境 JWT_SECRET 至少 32 字符且不得使用示例值")
        if "*" in self.cors_origin_list:
            raise ValueError("生产环境 CORS_ORIGINS 不允许通配符")
        if self.user_api_token and len(self.user_api_token.get_secret_value()) < 32:
            raise ValueError("生产环境 USER_API_TOKEN 至少 32 字符")
        if not self.normalized_root_domain:
            raise ValueError("生产环境必须配置 ROOT_DOMAIN 以启用子域名租户隔离")
        if not self.platform_admin_subdomain.strip():
            raise ValueError("生产环境必须配置 PLATFORM_ADMIN_SUBDOMAIN")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取进程级配置单例。"""
    return Settings()  # type: ignore[call-arg]


def reset_settings() -> None:
    """清空配置缓存（测试或切换环境时使用）。"""
    get_settings.cache_clear()
