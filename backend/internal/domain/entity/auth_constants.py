"""应用授权 MVP 枚举常量。

与产品方案对齐：
- auth_source: OPS（运营直接开通） / MARKET_APPLY（市场申请单关联开通）
- auth_type: FORMAL / TRIAL / GIFT
- auth_status: WAIT_EFFECT / ACTIVE / EXPIRED / RECYCLED
- apply_type: TRIAL / BUY
- apply_status: SUBMITTED / HANDLING / PASS / REJECT / FINISH
- sale_mode: 1=仅运营后台开通；2=市场可见+可申请
"""

from __future__ import annotations

from enum import Enum


class AuthSource(str, Enum):
    OPS = "OPS"
    MARKET_APPLY = "MARKET_APPLY"


class AuthType(str, Enum):
    FORMAL = "FORMAL"
    TRIAL = "TRIAL"
    GIFT = "GIFT"


class AuthStatus(str, Enum):
    WAIT_EFFECT = "WAIT_EFFECT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RECYCLED = "RECYCLED"


class ApplyType(str, Enum):
    TRIAL = "TRIAL"
    BUY = "BUY"


class ApplyStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    HANDLING = "HANDLING"
    PASS = "PASS"
    REJECT = "REJECT"
    FINISH = "FINISH"


class SaleMode(int, Enum):
    OPS_ONLY = 1
    MARKET = 2


class AuthOperation(str, Enum):
    """auth_operation_log 操作类型。"""
    CREATE = "CREATE"
    RECYCLE = "RECYCLE"
    RENEW = "RENEW"
    EXPIRE = "EXPIRE"
    ACTIVATE = "ACTIVATE"
    APPLY_SUBMIT = "APPLY_SUBMIT"
    APPLY_HANDLING = "APPLY_HANDLING"
    APPLY_REJECT = "APPLY_REJECT"
    APPLY_PASS = "APPLY_PASS"
    APPLY_FINISH = "APPLY_FINISH"


# MVP 校验规则：同一 tenant + app 只允许 1 条 ACTIVE
# 定时任务每小时扫一次 WAIT_EFFECT / EXPIRED
AUTH_CACHE_TTL_SECONDS = 180  # 3 分钟
AUTH_CACHE_KEY_PREFIX = "auth"
