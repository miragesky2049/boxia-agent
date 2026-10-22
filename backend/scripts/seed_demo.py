"""写入本地演示数据（仅开发/演示环境，幂等；资源归属产品级平台）。"""

import sys

from sqlalchemy import text

from internal.infrastructure.model.database import dispose_engine, get_engine

_DEMO_RESOURCES = {
    "skills": [
        ("知识检索", "从知识库检索相关文档片段", "SELECT ...", "{}"),
        ("意图识别", "识别用户问题意图", "class Intent ...", "{}"),
    ],
    "tools": [
        ("天气查询", "查询指定城市天气", "http", '{"method": "GET"}'),
        ("工单创建", "创建售后工单", "http", '{"method": "POST"}'),
    ],
    "components": [
        ("信息卡片", "展示结构化信息", "card", "{}"),
        ("快捷操作", "展示操作按钮组", "actions", "{}"),
    ],
    "prompts": [
        ("客服问候", "客服首轮问候语", "你好，我是智能助手", "[]", "chat"),
        ("摘要生成", "生成对话摘要", "请总结以下内容：{{content}}", '["content"]', "summary"),
    ],
}


def main() -> int:
    """按名称幂等补充演示资源。"""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            for table, rows in _DEMO_RESOURCES.items():
                for row in rows:
                    name = row[0]
                    exists = conn.execute(
                        text(
                            f"SELECT 1 FROM {table} "
                            "WHERE lower(name) = lower(:name) AND tenant_id IS NULL"
                        ),
                        {"name": name},
                    ).first()
                    if exists:
                        continue
                    if table == "prompts":
                        conn.execute(
                            text(
                                "INSERT INTO prompts "
                                "(name, description, content, variables, category) "
                                "VALUES (:name, :desc, :content, CAST(:variables AS JSONB), :category)"
                            ),
                            {
                                "name": row[0],
                                "desc": row[1],
                                "content": row[2],
                                "variables": row[3],
                                "category": row[4],
                            },
                        )
                    elif table == "skills":
                        conn.execute(
                            text(
                                "INSERT INTO skills (name, description, content, config) "
                                "VALUES (:name, :desc, :content, CAST(:config AS JSONB))"
                            ),
                            {
                                "name": row[0],
                                "desc": row[1],
                                "content": row[2],
                                "config": row[3],
                            },
                        )
                    else:
                        conn.execute(
                            text(
                                f"INSERT INTO {table} (name, description, type, config) "
                                "VALUES (:name, :desc, :type, CAST(:config AS JSONB))"
                            ),
                            {
                                "name": row[0],
                                "desc": row[1],
                                "type": row[2],
                                "config": row[3],
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
