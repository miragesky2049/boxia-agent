"""写入本地演示数据（仅开发/演示环境，幂等；工具归属产品级平台）。"""

import json
import sys

from sqlalchemy import text

from internal.infrastructure.id.uuid7 import new_uuid
from internal.infrastructure.model.database import dispose_engine, get_engine

# (name, description, config)
_DEMO_TOOLS = (
    ("天气查询", "查询指定城市天气", {"method": "GET"}),
    ("工单创建", "创建售后工单", {"method": "POST"}),
)


def main() -> int:
    """按名称幂等补充产品级演示工具。"""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            for name, description, extra_config in _DEMO_TOOLS:
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM resource "
                        "WHERE type = 'tool' AND owner_type = 'platform' "
                        "AND lower(name) = lower(:name)"
                    ),
                    {"name": name},
                ).first()
                if exists:
                    continue
                config = {"description": description, **extra_config}
                conn.execute(
                    text(
                        "INSERT INTO resource (id, type, owner_type, owner_id, name, config) "
                        "VALUES (:id, 'tool', 'platform', NULL, :name, CAST(:config AS JSONB))"
                    ),
                    {
                        "id": new_uuid(),
                        "name": name,
                        "config": json.dumps(config),
                    },
                )
        print("演示数据写入完成")
    except Exception as exc:  # 演示脚本需要给出可读失败原因
        print(f"写入演示数据失败: {exc}", file=sys.stderr)
        return 1
    finally:
        dispose_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
