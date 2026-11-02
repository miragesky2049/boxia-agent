"""coze 画布字段名映射配置。

把硬编码的字段名提取成配置，coze 改字段名时只改这里。
来源：coze-studio/frontend/packages/workflow/base/src/types/dto.ts
"""

from __future__ import annotations

# 边字段映射：coze 大写字段名 → 内部小写字段名
EDGE_FIELD_MAP = {
    "sourceNodeID": "source",
    "sourceNodeId": "source",
    "targetNodeID": "target",
    "targetNodeId": "target",
    "sourcePortID": "source_port",
    "sourcePortId": "source_port",
}

# 节点 data 下的标准字段（不压入 config）
NODE_STANDARD_INPUT_FIELDS = {
    "inputParameters",      # 运行时入参
    "settingOnError",       # 错误处理策略
}

# ValueExpressionDTO 的字段名
VALUE_EXPRESSION_TYPES = ("literal", "ref", "object_ref")

# Ref 表达式的 source 类型
REF_SOURCE_BLOCK_OUTPUT = "block-output"
REF_SOURCE_VARIABLE = "variable"
REF_SOURCE_GLOBAL_PREFIX = "global_variable_"

# 节点类型字符串 → NodeType 枚举的映射表（coze StandardNodeType）
# 如果 coze 新增节点类型，先在这里加映射，convert 就能识别
NODE_TYPE_MAP = {
    "1": "START",
    "2": "END",
    "3": "LLM",
    "4": "API",
    "5": "CODE",
    "6": "DATASET",
    "8": "IF",
    "9": "SUB_WORKFLOW",
    "11": "VARIABLE",
    "12": "DATABASE",
    "13": "OUTPUT",
    "15": "TEXT",
    "18": "QUESTION",
    "19": "BREAK",
    "20": "SET_VARIABLE",
    "21": "LOOP",
    "22": "INTENT",
    "23": "IMAGE_CANVAS",
    "24": "SCENE_VARIABLE",
    "25": "SCENE_CHAT",
    "26": "LTM",
    "27": "DATASET_WRITE",
    "28": "BATCH",
    "29": "CONTINUE",
    "30": "INPUT",
    "31": "COMMENT",
    "32": "VARIABLE_MERGE",
    "37": "QUERY_MESSAGE_LIST",
    "38": "CLEAR_CONTEXT",
    "39": "CREATE_CONVERSATION",
    "40": "VARIABLE_ASSIGN",
    "42": "DATABASE_UPDATE",
    "43": "DATABASE_QUERY",
    "44": "DATABASE_DELETE",
    "45": "HTTP",
    "46": "DATABASE_CREATE",
    "51": "UPDATE_CONVERSATION",
    "52": "DELETE_CONVERSATION",
    "53": "QUERY_CONVERSATION_LIST",
    "54": "QUERY_CONVERSATION_HISTORY",
    "55": "CREATE_MESSAGE",
    "56": "UPDATE_MESSAGE",
    "57": "DELETE_MESSAGE",
    "58": "JSON_STRINGIFY",
    "59": "JSON_PARSER",
    # 本地扩展段位（coze 未公开/依赖外部服务）
    "211": "DATASET_DELETE",
    "212": "ASYNC_TASK",
    "213": "IMAGE_GENERATE",
    "214": "IMAGE_CUTOUT",
    "215": "PROMPT_OPTIMIZE",
    "216": "IMAGE_ENHANCE",
    "217": "VIDEO_GENERATE",
    "218": "VIDEO_EXTRACT_AUDIO",
    "219": "VIDEO_FRAME",
}
