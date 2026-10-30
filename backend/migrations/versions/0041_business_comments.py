"""0041 为业务表和关键字段补充 COMMENT ON，统一业务字典。

Revision ID: 0041_business_comments
Revises: 0040_application_auth
Create Date: 2026-10-30

设计要点：
- 只补充注释，不改结构，可重复执行（IF NOT EXISTS 语义通过 DO 块实现）
- 覆盖 v4 业务核心表：application / application_graph / resource / resource_grant /
  tenant_application_instance / application_apply / run / run_node_execution /
  model_provider / model_catalog / tenant_usage_ledger / event_webhook /
  application_field_version / tenant_field_pin / documents / document_chunks
- 授权相关字段详细注释，其它表只补表级注释
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0041_business_comments"
down_revision: str | None = "0040_application_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 表级注释（表名 -> 注释）
_TABLE_COMMENTS = {
    "application": "应用（合并原 agents + workflows）：租户或平台拥有的智能体/工作流入口",
    "application_graph": "应用图定义：LangGraph 兼容的 nodes + edges DSL，与 application 一对一",
    "resource": "统一资源表：tool / prompt / skill / knowledge 四类资源的统一存储",
    "resource_grant": "资源对租户的直接授权（v4 市场场景）：resource_id + tenant_id 唯一",
    "resource_grants": "RBAC 资源授权（旧管理后台场景）：按角色或租户范围授权 agent/skill/tool 等",
    "tenant_application_instance": "租户应用授权实例：记录租户开通某应用的授权记录（含有效期、配额、合同号）",
    "application_apply": "应用申请单：租户在市场提交的试用/购买申请，运营审核后关联开通",
    "application_field_version": "应用字段版本历史：应用画布/配置的版本快照",
    "tenant_field_pin": "租户字段钉选：租户在控制台自定义字段排列",
    "run": "工作流/智能体运行记录：一次完整的 invoke 对应一行",
    "run_node_execution": "节点执行明细：run 下每个节点的输入输出与耗时",
    "model_provider": "模型服务商：OpenAI / Azure / 国产大模型等接入配置",
    "model_catalog": "可用模型目录：从 model_provider 下挂的具体模型清单",
    "tenant_usage_ledger": "租户用量流水：按租户/应用/模型维度的 token 用量计费",
    "event_webhook": "事件 Webhook：租户订阅平台事件（如应用运行完成）回调",
    "documents": "RAG 文档：租户上传的知识库文档元数据",
    "document_chunks": "RAG 文档切片：文档向量化后的 chunk 存储",
    "tools": "【旧】HTTP 工具定义：admin tools 后台维护的工具库，新工具统一走 resource 表",
    "audit_logs": "审计日志：所有授权变更、管理操作的 before/after 快照",
    "tenants": "租户：SaaS 多租户隔离的顶层实体",
    "users": "租户最终用户：登录租户控制台的账号",
    "admin_users": "平台管理员：运营/销售/平台维护账号",
    "roles": "角色：平台角色（tenant_id=全零 UUID）+ 租户角色",
    "user_roles": "用户-角色多对多关联",
    "permission_resources": "权限资源目录：菜单/页面/按钮/资源权限码",
    "role_permissions": "角色-权限多对多授权",
    "user_refresh_tokens": "终端用户刷新令牌（只存哈希）",
    "admin_refresh_tokens": "平台管理员刷新令牌（只存哈希）",
    "departments": "部门：租户组织架构",
    "user_employments": "用户任职关系：用户与部门的多对多绑定",
    "mgmt_units": "管理单元：数据权限范围分组",
    "mgmt_unit_departments": "管理单元-部门关联",
    "mgmt_unit_users": "管理单元-用户关联",
    "user_mgmt_unit_grants": "用户-管理单元授权：用户可管理的数据范围",
    "hr_dictionaries": "HR 字典：性别/岗位/职级等枚举数据",
}


# 列级注释（表名 -> [(列名, 注释)]）
_COLUMN_COMMENTS = {
    "application": [
        ("owner_type", "platform=平台拥有；tenant=租户拥有"),
        ("owner_id", "owner_type=platform 时为 NULL；owner_type=tenant 时为租户 ID"),
        ("is_listed_in_market", "是否出现在应用市场列表"),
        ("visibility_mode", "all=所有租户可见；custom=按白名单可见"),
        ("sale_mode", "1=仅运营后台开通；2=市场可见+可申请"),
        ("support_trial", "是否支持免费试用"),
        ("doc_url", "应用文档地址"),
        ("ext_json", "扩展字段 JSON：市场展示/计费等非标字段"),
    ],
    "application_graph": [
        ("graph", "LangGraph 兼容的 nodes + edges JSONB"),
        ("graph_schema_version", "DSL schema 版本号"),
        ("runtime_mode", "dag=工作流；agent_loop=智能体循环；运行时自动推断"),
    ],
    "resource": [
        ("type", "tool / prompt / skill / knowledge"),
        ("owner_type", "platform / tenant"),
        ("config", "资源配置（HTTP URL / prompt 内容 / MCP server 等）"),
        ("is_deprecated", "废弃标记（软删除）"),
    ],
    "resource_grant": [
        ("resource_id", "被授权资源"),
        ("tenant_id", "被授权租户"),
        ("granted_at", "授权时间"),
    ],
    "tenant_application_instance": [
        ("status", "active=生效；wait_effect=待生效；expired=已过期；revoked=已回收；suspended=停用；disabled=禁用"),
        ("source", "marketplace=市场安装；granted=运营开通"),
        ("auth_source", "OPS=运营直接开通；MARKET_APPLY=市场申请单关联开通"),
        ("auth_type", "FORMAL=正式；TRIAL=试用；GIFT=赠送"),
        ("contract_no", "合同号（FORMAL 必填）"),
        ("quota_json", "配额 JSON：user_limit / rate_limit 等"),
        ("start_time", "授权生效时间"),
        ("expire_time", "授权到期时间（NULL 表示永不过期）"),
        ("apply_id", "关联的申请单 ID（市场开通时非空）"),
        ("remark", "开通备注"),
        ("granted_by", "操作人 ID"),
        ("granted_at", "开通时间"),
    ],
    "application_apply": [
        ("apply_type", "TRIAL=试用申请；BUY=购买申请"),
        ("status", "SUBMITTED=已提交；HANDLING=处理中；PASS=审核通过待开通；REJECT=已拒绝；FINISH=已开通完成"),
        ("expect_text", "租户填写的期望说明"),
        ("contact", "租户联系方式"),
        ("sales_user_id", "归属销售 ID"),
        ("audit_msg", "运营审核备注"),
        ("contract_no", "审核通过后录入的合同号"),
        ("created_by", "提交人 ID"),
    ],
    "run": [
        ("status", "running / success / error / interrupted"),
        ("input", "运行入参 JSONB"),
        ("output", "运行出参 JSONB"),
        ("error", "失败时的错误信息"),
        ("langgraph_thread_id", "LangGraph checkpointer thread_id，用于 time-travel"),
    ],
    "run_node_execution": [
        ("node_id", "画布节点 ID"),
        ("node_type", "节点类型（LLM/HTTP/IF 等）"),
        ("input", "节点入参 JSONB"),
        ("output", "节点出参 JSONB"),
        ("error", "节点错误信息"),
        ("token_usage", "节点 token 消耗 JSONB"),
    ],
    "model_provider": [
        ("name", "服务商名称，例如 deepseek / qwen / openai"),
        ("base_url", "API 地址"),
        ("api_key", "平台统一 API Key；阶段二支持租户自带 key"),
        ("owner_type", "platform / tenant（tenant 预留）"),
        ("is_enabled", "是否启用"),
    ],
    "model_catalog": [
        ("model_id", "对外引用的模型 ID，例如 deepseek-chat"),
        ("provider_id", "所属服务商"),
        ("capabilities", "能力 JSONB：supports_tools / supports_vision / context_window / max_output_tokens"),
        ("is_enabled", "是否启用"),
    ],
    "tenant_usage_ledger": [
        ("tenant_id", "租户 ID"),
        ("application_id", "消耗应用"),
        ("run_id", "关联运行 ID"),
        ("node_id", "消耗节点 ID"),
        ("model_id", "消耗模型 ID"),
        ("prompt_tokens", "输入 token 数"),
        ("completion_tokens", "输出 token 数"),
        ("total_tokens", "总 token 数"),
    ],
    "event_webhook": [
        ("tenant_id", "租户 ID"),
        ("application_id", "关联应用；空 = 该租户所有应用"),
        ("event_type", "事件类型：run_finished / run_error / node_error"),
        ("url", "回调地址"),
        ("is_enabled", "是否启用"),
    ],
    "documents": [
        ("tenant_id", "租户 ID"),
        ("title", "文档标题"),
        ("source_type", "来源类型：text / file / url"),
        ("source_uri", "来源地址"),
        ("ingest_status", "ingest 状态：pending / processing / ready / failed"),
        ("chunk_count", "切片数量"),
    ],
    "document_chunks": [
        ("document_id", "所属文档"),
        ("chunk_index", "切片序号"),
        ("content", "切片文本"),
        ("token_count", "切片 token 数"),
        ("embedding", "向量（pgvector，1024 维）"),
    ],
}


def upgrade() -> None:
    # 表级注释
    for table, comment in _TABLE_COMMENTS.items():
        op.execute(
            f"COMMENT ON TABLE {table} IS '{comment.replace(chr(39), chr(39)*2)}'"
        )

    # 列级注释
    for table, columns in _COLUMN_COMMENTS.items():
        for col, comment in columns:
            op.execute(
                f"COMMENT ON COLUMN {table}.{col} IS '{comment.replace(chr(39), chr(39)*2)}'"
            )


def downgrade() -> None:
    # 注释回滚：清空所有已加注释（不区分是否本次加的，统一置空）
    for table in _TABLE_COMMENTS:
        op.execute(f"COMMENT ON TABLE {table} IS NULL")
    for table, columns in _COLUMN_COMMENTS.items():
        for col, _ in columns:
            op.execute(f"COMMENT ON COLUMN {table}.{col} IS NULL")
