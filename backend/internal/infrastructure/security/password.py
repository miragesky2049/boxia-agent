"""密码哈希（bcrypt）与强度校验。"""

from functools import lru_cache

import bcrypt

from internal.application.errors import ValidationError
from internal.infrastructure.config.settings import get_settings

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_BYTES = 72
_COMMON_PASSWORDS = {
    "123456789012",
    "password1234",
    "admin1234567",
    "qwerty123456",
    "abcd12345678",
    "password@123",
}


def hash_password(plain_password: str) -> str:
    """生成 bcrypt 哈希。"""
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode(
        "utf-8"
    )


def verify_password(plain_password: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配，非法哈希返回 False。"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """用于未知用户登录的固定耗时校验，避免用户名枚举。"""
    return hash_password("boxia-dummy-password-not-used")


def validate_password_strength(password: str, username: str) -> None:
    """校验密码策略：长度、字符类别、常见弱口令与用户名包含。"""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"密码长度至少 {MIN_PASSWORD_LENGTH} 位")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValidationError(f"密码不能超过 {MAX_PASSWORD_BYTES} 字节")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValidationError("密码过于常见，请更换更复杂的密码")

    categories = sum(
        (
            any(char.islower() for char in password),
            any(char.isupper() for char in password),
            any(char.isdigit() for char in password),
            any(not char.isalnum() for char in password),
        )
    )
    if categories < 3:
        raise ValidationError("密码需包含大小写字母、数字、符号中的至少三类")
    if username and username.lower() in password.lower():
        raise ValidationError("密码不能包含用户名")
