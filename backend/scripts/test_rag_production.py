"""生产级 RAG 全链路验证：多文档 → ingest → 多 query 改写 → rerank 精排。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from internal.infrastructure.config.settings import get_settings
from internal.domain.entity.request_context import RequestContext
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.application.document_service import DocumentService
from internal.application.ingestion_service import IngestionService
from internal.application.retrieval_service import RetrievalService
from internal.domain.llm.client import OpenAICompatLLMClient
from internal.domain.retrieval.query_rewrite import LLMQueryRewriter
from internal.domain.retrieval.rerank import SiliconFlowRerankClient


# 4 份 markdown 格式测试文档（带 # 标题）
DOCUMENTS = [
    {
        "title": "公司请假制度(MD)",
        "source_type": "markdown",
        "content": """# 公司请假制度

## 第一章 总则

为规范公司请假管理，保障员工合法权益，特制定本制度。本制度适用于公司全体正式员工。

## 第二章 各类假期规定

### 年假

员工累计工作已满1年不满10年的，年休假5天；已满10年不满20年的，年休假10天；已满20年的，年休假15天。国家法定休假日、休息日不计入年休假假期。

### 病假

员工因病需要休假的，应提供二级以上医院出具的病假证明。病假期间工资按当地最低工资标准的80%发放。

### 婚假与产假

员工达到法定结婚年龄结婚的，可享受3天婚假。女员工生育享受98天产假，其中产前可以休假15天；难产的，增加产假15天。男员工陪产假为15天。
""",
    },
    {
        "title": "差旅报销制度(MD)",
        "source_type": "markdown",
        "content": """# 差旅报销制度

## 交通费用

高铁/动车：部门经理及以下级别可乘坐二等座，总监及以上级别可乘坐一等座。普通员工出差原则上不乘坐飞机。

## 住宿费用

一线城市（北京、上海、广州、深圳）：普通员工每人每天不超过400元。二线城市：不超过300元。三线及以下城市：不超过200元。

## 伙食补助

出差期间伙食补助按出差自然天数计算，不分地区每人每天100元。出差期间由接待单位统一安排伙食的，不报销伙食补助。

## 报销流程

员工出差结束后5个工作日内提交报销申请，附机票/车票、住宿发票等凭证。财务部门在收到完整报销材料后10个工作日内完成审核并打款。
""",
    },
    {
        "title": "IT设备采购规范(MD)",
        "source_type": "markdown",
        "content": """# IT设备采购规范

## 设备采购流程

各部门根据工作需要提出IT设备采购申请。采购申请需经部门负责人审批，再由IT部门审核配置合理性，最终报行政副总裁批准。

## 标准配置

新入职员工的电脑由IT部门统一配置。普通员工i5/16G/512G SSD，开发岗位i7/32G/1T SSD。

## 离职归还

员工离职时必须归还所有IT设备，包括电脑、显示器、键盘鼠标等。IT部门检查设备完好性后办理归还手续。
""",
    },
    {
        "title": "绩效考核办法(MD)",
        "source_type": "markdown",
        "content": """# 绩效考核办法

## 考核等级

绩效考核结果分为S（优秀）、A（良好）、B（合格）、C（待改进）、D（不合格）五个等级。

## 强制分布

S级不超过总人数的10%，A级不超过20%，B级约占60%，C级和D级合计不低于10%。

## 结果应用

连续两个季度考核为D级的员工，公司有权解除劳动合同。年度考核为S级的员工，优先获得晋升资格和调薪机会。
""",
    },
]


QUERIES = [
    # 应命中"请假制度"
    ("年假有多少天", "请假"),
    ("结婚能休多久假", "请假"),
    ("女人生孩子产假多长时间", "请假"),
    # 应命中"差旅"
    ("出差住宿标准是多少", "差旅"),
    ("出差伙食补助每天多少钱", "差旅"),
    # 应命中"IT设备"
    ("开发岗位电脑配置是什么", "IT设备"),
    ("离职时电脑要还吗", "IT设备"),
    # 应命中"绩效"
    ("绩效考核等级有哪些", "绩效"),
    ("连续两个季度不合格会怎样", "绩效"),
    # 不相关
    ("附近有什么好吃的", "无关"),
    ("今天天气怎么样", "无关"),
    # 指代类（需要历史感知）
    (
        "那婚假呢",
        "请假(指代)",
        [{"role": "user", "content": "年假有多少天"}, {"role": "assistant", "content": "年假根据工龄5-15天不等。"}],
    ),
]


async def main() -> None:
    settings = get_settings()
    ctx = RequestContext(
        scope="platform", tenant=None, host="platform.localhost", resolution="default"
    )

    print("=" * 60)
    print("第一步：清空旧文档，上传 4 份 markdown 文档并 ingest")
    print("=" * 60)

    # 清空旧文档
    uow = SqlAlchemyUnitOfWork(tenant_id=None)
    try:
        svc = DocumentService(uow, ctx)
        page = svc.list(1, 100, keyword=None)
        for doc in page.items:
            svc.delete(doc.id)
        print(f"已清空 {len(page.items)} 个旧文档")
    finally:
        uow.close()

    # 上传 + ingest
    for doc in DOCUMENTS:
        uow = SqlAlchemyUnitOfWork(tenant_id=None)
        try:
            doc_service = DocumentService(uow, ctx)
            ing_service = IngestionService(uow, ctx)
            created = doc_service.create(
                title=doc["title"],
                source_type=doc["source_type"],
                content=doc["content"],
            )
            count = await ing_service.ingest(
                document_id=created.id,
                raw_text=doc["content"],
                chunk_size=settings.rag_chunk_size,
                chunk_overlap=settings.rag_chunk_overlap,
                source_type=doc["source_type"],
            )
            print(f"  {doc['title']}: {count} chunks")
        finally:
            uow.close()

    print("\n" + "=" * 60)
    print("第二步：构造 rerank + query_rewriter 客户端，跑检索")
    print("=" * 60)

    rerank_client = SiliconFlowRerankClient(
        api_key=settings.embedding_api_key.get_secret_value(),
        model=settings.rag_rerank_model,
        base_url=settings.embedding_base_url,
        timeout_seconds=settings.embedding_timeout_seconds,
    )
    llm = OpenAICompatLLMClient(
        api_key=settings.llm_api_key.get_secret_value(),
        model=settings.llm_model_id,
        base_url=settings.llm_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    rewriter = LLMQueryRewriter(llm)

    uow = SqlAlchemyUnitOfWork(tenant_id=None)
    try:
        retrieval = RetrievalService(
            uow,
            ctx,
            rerank_client=rerank_client,
            query_rewriter=rewriter,
        )
        for item in QUERIES:
            query, expected = item[0], item[1]
            history = item[2] if len(item) > 2 else []
            result = await retrieval.search(
                query=query,
                history=history,
                top_k=settings.rag_top_k,
                similarity_threshold=settings.rag_similarity_threshold,
                enable_query_rewrite=True,
                enable_rerank=True,
                variant_count=settings.rag_query_rewrite_variants,
                recall_multiplier=settings.rag_recall_multiplier,
            )
            print(f"\n查询: 「{query}」(期望: {expected})")
            print(f"  standalone: {result.standalone_query}")
            print(f"  recalled_queries: {result.recalled_queries}")
            if not result.chunks:
                print(f"  ❌ 无命中")
                continue
            for i, c in enumerate(result.chunks[:3]):
                heading = " > ".join(c.metadata.get("heading_path") or [])
                print(
                    f"  [{i+1}] rerank_score={c.rerank_score} heading={heading}"
                )
                print(f"      {c.content[:100].replace(chr(10), ' ')}...")
    finally:
        uow.close()


if __name__ == "__main__":
    asyncio.run(main())
