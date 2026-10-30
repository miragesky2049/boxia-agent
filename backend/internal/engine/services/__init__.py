"""GraphRuntime 依赖服务：llm / http / subgraph_loader 等基础设施适配。

节点 handler 通过 ctx.services.get(name) 拿依赖，本包负责把 domain 层期望的接口
与基础设施层（LLMClient / httpx / ApplicationService）对接起来。
"""
