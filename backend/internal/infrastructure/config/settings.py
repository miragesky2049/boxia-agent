"""应用配置：基于 pydantic-settings 分层加载并校验环境变量。"""

import ipaddress
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[3]
# 一级子域名标签：租户编码与平台子域名共用同一格式约束
_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_DOMAIN_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$"
)


def _is_ip_literal(value: str) -> bool:
    """判断字符串是否为 IP 地址字面量。"""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


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

    # local=本机调试，dev=开发环境部署，test=测试环境部署，prod=线上
    app_env: Literal["local", "dev", "test", "prod"] = "local"
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
    # 最终用户令牌使用独立受众，避免管理端与用户端令牌互相冒用
    user_jwt_audience: str = "boxia-user"
    access_token_minutes: int = Field(default=30, ge=1, le=120)
    refresh_token_days: int = Field(default=14, ge=1, le=90)

    bcrypt_rounds: int = Field(default=12, ge=4, le=16)
    login_max_attempts: int = Field(default=5, ge=1, le=20)
    login_lock_minutes: int = Field(default=15, ge=1, le=1440)

    # 密码策略唯一定义点：后端校验与前端表单均由此下发，禁止在业务代码中硬编码。
    # bcrypt 只处理前 72 字节，PASSWORD_MAX_BYTES 不允许超过 72。
    password_min_length: int = Field(default=12, ge=8, le=64)
    password_max_bytes: int = Field(default=72, ge=32, le=72)
    password_min_categories: int = Field(default=3, ge=1, le=4)

    # 技能包限制：文本类技能包，按文件数/单文件/总大小三重配额防止滥用。
    skill_package_max_files: int = Field(default=200, ge=1, le=2000)
    skill_package_max_file_bytes: int = Field(default=1_048_576, ge=1024, le=16_777_216)
    skill_package_max_total_bytes: int = Field(default=8_388_608, ge=1024, le=67_108_864)

    # 多租户根域名：每个环境使用独立泛域名，如 dev.example.com / test.example.com / example.com。
    # local 环境留空时回退 localhost，便于用 acme.localhost 直接验证子域名解析。
    root_domain: str = ""
    platform_admin_subdomain: str = "adminsystem"
    default_tenant_code: str = ""
    # 仅 local 环境允许用 X-Tenant-Code 请求头覆盖作用域；开发/测试/线上启动时禁止开启。
    allow_tenant_header: bool = False

    cors_origins: str = ""
    log_level: str = "INFO"
    log_json: bool | None = None
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "boxia-agent"
    otel_traces_sampler_ratio: float = Field(default=1.0, ge=0.0, le=1.0)

    docs_enabled: bool | None = None
    legacy_api_enabled: bool = True

    @property
    def is_prod(self) -> bool:
        """是否生产环境。"""
        return self.app_env == "prod"

    @property
    def is_local(self) -> bool:
        """是否本机调试环境。"""
        return self.app_env == "local"

    @property
    def cors_origin_list(self) -> list[str]:
        """解析逗号分隔的 CORS 白名单。"""
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def effective_log_json(self) -> bool:
        """日志格式：生产默认 JSON，可用 LOG_JSON 覆盖。"""
        return self.is_prod if self.log_json is None else self.log_json

    @property
    def effective_docs_enabled(self) -> bool:
        """API 文档：生产默认关闭。"""
        return not self.is_prod if self.docs_enabled is None else self.docs_enabled

    @property
    def normalized_root_domain(self) -> str:
        """规范化根域名；local 留空时回退 localhost，便于直接访问 *.localhost。"""
        domain = self.root_domain.strip().lower().strip(".")
        if not domain and self.is_local:
            return "localhost"
        return domain

    @property
    def platform_admin_host(self) -> str:
        """产品级平台主机名（不含端口）。"""
        subdomain = self.platform_admin_subdomain.strip().lower()
        root = self.normalized_root_domain
        return f"{subdomain}.{root}" if root else subdomain

    @model_validator(mode="after")
    def _validate_environment(self) -> "Settings":
        """按环境校验租户域名配置，避免带病启动或静默回退产品级平台。"""
        subdomain = self.platform_admin_subdomain.strip().lower()
        if not _LABEL_PATTERN.match(subdomain):
            raise ValueError("PLATFORM_ADMIN_SUBDOMAIN 必须是一级子域名标签")

        if self.password_min_length > self.password_max_bytes:
            raise ValueError("PASSWORD_MIN_LENGTH 不能大于 PASSWORD_MAX_BYTES")

        root = self.normalized_root_domain
        if self.is_local:
            if root and not _DOMAIN_PATTERN.match(root):
                raise ValueError("ROOT_DOMAIN 格式不正确，例如 example.com 或 localhost")
            return self

        if not root:
            raise ValueError(f"{self.app_env} 环境必须配置 ROOT_DOMAIN 以启用子域名租户隔离")
        if "." not in root or root == "localhost" or root.endswith(".localhost"):
            raise ValueError("部署环境 ROOT_DOMAIN 必须是完整域名，例如 dev.example.com")
        if _is_ip_literal(root):
            raise ValueError("部署环境 ROOT_DOMAIN 不能是 IP 地址")
        if self.allow_tenant_header:
            raise ValueError("仅 local 环境允许开启 ALLOW_TENANT_HEADER")

        if not self.is_prod:
            return self

        secret = self.jwt_secret.get_secret_value()
        if len(secret) < 32 or secret in INSECURE_SECRETS:
            raise ValueError("生产环境 JWT_SECRET 至少 32 字符且不得使用示例值")
        if "*" in self.cors_origin_list:
            raise ValueError("生产环境 CORS_ORIGINS 不允许通配符")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取进程级配置单例。"""
    return Settings()  # type: ignore[call-arg]


def reset_settings() -> None:
    """清空配置缓存（测试或切换环境时使用）。"""
    get_settings.cache_clear()
