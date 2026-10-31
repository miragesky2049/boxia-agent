"""节点类型枚举：与 coze 画布 StandardNodeType 数字字符串对齐。

来源：coze-studio/frontend/packages/workflow/base/src/types/node-type.ts
未在本项目实现的类型保留枚举值，convert 阶段会显式报错或忽略。
"""

from __future__ import annotations

from enum import Enum


class NodeType(str, Enum):
    # 基础节点
    START = "1"
    END = "2"
    LLM = "3"
    API = "4"            # 插件 / 工具调用
    CODE = "5"           # 代码沙箱
    DATASET = "6"        # 知识库检索
    IF = "8"             # 条件分支
    SUB_WORKFLOW = "9"   # 子图调用
    VARIABLE = "11"      # 旧版变量节点（废弃）
    DATABASE = "12"      # 数据库节点（本项目砍掉，用 HTTP 替代）
    OUTPUT = "13"
    TEXT = "15"          # 文本处理
    QUESTION = "18"
    BREAK = "19"         # loop 内 break
    SET_VARIABLE = "20"
    LOOP = "21"
    INTENT = "22"
    LTM = "26"           # 长期记忆
    DATASET_WRITE = "27"
    BATCH = "28"
    CONTINUE = "29"      # loop 内 continue
    INPUT = "30"
    COMMENT = "31"
    VARIABLE_MERGE = "32"
    QUERY_MESSAGE_LIST = "37"
    CLEAR_CONTEXT = "38"
    CREATE_CONVERSATION = "39"
    VARIABLE_ASSIGN = "40"
    DATABASE_UPDATE = "42"
    DATABASE_QUERY = "43"
    DATABASE_DELETE = "44"
    HTTP = "45"
    DATABASE_CREATE = "46"
    UPDATE_CONVERSATION = "51"
    DELETE_CONVERSATION = "52"
    QUERY_CONVERSATION_LIST = "53"
    QUERY_CONVERSATION_HISTORY = "54"
    CREATE_MESSAGE = "55"
    UPDATE_MESSAGE = "56"
    DELETE_MESSAGE = "57"
    JSON_STRINGIFY = "58"
    JSON_PARSER = "59"
    HUMAN_APPROVAL = "60"  # 人审节点（本次 stub，后续补 interrupt + resume）

    # A6：Agent 循环节点（coze 标准没有数字编码，本项目自定义 100）
    # 走 plan/execute/reflect 三阶段协议，非 DAG 执行
    AGENT_LOOP = "100"


# 本项目当前阶段不实现的节点类型（convert 时显式报错）
# 数据库类已决策砍掉，用 HTTP 节点调自己的 API 替代。
# Question / Intent / LTM 等留待后续阶段。
# Dataset(6) / DatasetWrite(27) 已恢复，走向量库抽象层（Milvus / PGVector）。
UNSUPPORTED_TYPES: frozenset[NodeType] = frozenset(
    {
        NodeType.DATABASE,
        NodeType.DATABASE_UPDATE,
        NodeType.DATABASE_QUERY,
        NodeType.DATABASE_DELETE,
        NodeType.DATABASE_CREATE,
        NodeType.OUTPUT,
        NodeType.INTENT,
        NodeType.LTM,
        NodeType.VARIABLE,
        NodeType.QUESTION,
    }
)
