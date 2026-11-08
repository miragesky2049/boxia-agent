"""多主题 RAG 检索验证脚本：上传不同主题文档，测试阈值过滤效果。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 把 backend 目录加入 sys.path，便于直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from internal.application.document_service import DocumentService
from internal.application.ingestion_service import IngestionService
from internal.application.retrieval_service import RetrievalService
from internal.domain.entity.request_context import RequestContext
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork

# ── 多主题测试文档 ──────────────────────────────────────────────
DOCUMENTS = [
    {
        "title": "公司请假制度",
        "source_type": "text",
        "content": """公司请假管理制度
第一章 总则
第一条 为规范公司请假管理，保障员工合法权益，特制定本制度。
第二条 本制度适用于公司全体正式员工、试用期员工及实习生。

第二章 各类假期规定
第三条 年假：员工累计工作已满1年不满10年的，年休假5天；已满10年不满20年的，年休假10天；已满20年的，年休假15天。国家法定休假日、休息日不计入年休假假期。
第四条 病假：员工因病需要休假的，应提供二级以上医院出具的病假证明。病假期间工资按当地最低工资标准的80%发放。
第五条 婚假：员工达到法定结婚年龄结婚的，可享受3天婚假。晚婚（男25周岁、女23周岁以上初婚）增加15天婚假。
第六条 产假：女员工生育享受98天产假，其中产前可以休假15天；难产的，增加产假15天；生育多胞胎的，每多生育1个婴儿，增加产假15天。男员工陪产假为15天。
第七条 丧假：员工直系亲属（父母、配偶、子女）去世，给予3天丧假；祖父母、外祖父母去世，给予1天丧假。
第八条 事假：员工因私事需要请假的，可请事假。事假期间不计发工资。事假全年累计不得超过20天。

第三章 请假流程
第九条 员工请假需提前在OA系统提交申请，按审批权限逐级审批。
第十条 请假1天以内的，由直接上级审批；请假1-3天的，由部门负责人审批；请假3天以上的，由分管副总裁审批。
""",
    },
    {
        "title": "差旅报销制度",
        "source_type": "text",
        "content": """公司差旅费用报销管理制度
第一章 总则
第一条 为规范员工因公出差的费用管理，合理控制差旅成本，特制定本制度。
第二条 本制度适用于公司全体员工因公出差的费用报销。

第二章 交通费用标准
第三条 高铁/动车：部门经理及以下级别可乘坐二等座，总监及以上级别可乘坐一等座。
第四条 飞机：总监及以上级别可乘坐经济舱，紧急情况下经分管副总裁批准可乘坐商务舱。普通员工出差原则上不乘坐飞机。
第五条 市内交通：出差期间市内交通费用实报实销，每人每天不超过100元。优先选择公共交通。

第三章 住宿费用标准
第六条 一线城市（北京、上海、广州、深圳）：普通员工每人每天不超过400元，经理及以下不超过500元，总监及以上不超过800元。
第七条 二线城市：普通员工每人每天不超过300元，经理及以下不超过400元，总监及以上不超过600元。
第八条 三线及以下城市：普通员工每人每天不超过200元，经理及以下不超过300元，总监及以上不超过500元。

第四章 伙食补助标准
第九条 出差期间伙食补助按出差自然（日历）天数计算，不分地区每人每天100元。
第十条 出差期间由接待单位统一安排伙食的，不报销伙食补助。

第五章 报销流程
第十一条 员工出差结束后5个工作日内提交报销申请，附机票/车票、住宿发票等凭证。
第十二条 财务部门在收到完整报销材料后10个工作日内完成审核并打款。
第十三条 未按审批程序擅自出差的，相关费用由个人承担。
""",
    },
    {
        "title": "IT设备采购与领用规范",
        "source_type": "text",
        "content": """公司IT设备采购与领用管理规范
第一章 总则
第一条 为规范公司IT设备的采购、分配和报废流程，提高设备使用效率，保障信息安全，特制定本规范。

第二章 设备采购
第二条 各部门根据工作需要提出IT设备采购申请，填写《IT设备采购申请表》，注明设备类型、配置要求、使用人。
第三条 采购申请需经部门负责人审批，再由IT部门审核配置合理性，最终报行政副总裁批准。
第四条 IT设备供应商由IT部门统一管理，每年度进行供应商评估和比价。

第三章 设备领用
第五条 新入职员工的电脑由IT部门统一配置。标准配置为：普通员工i5/16G/512G SSD，开发岗位i7/32G/1T SSD。
第六条 员工领用设备时需在《IT设备领用登记单》上签字确认，注明设备编号、型号、配置。
第七条 员工岗位变动时，应及时办理设备变更或归还手续。

第四章 设备使用与维护
第八条 员工不得擅自拆卸、改装公司IT设备，不得安装未经IT部门审核的软件。
第九条 公司所有电脑必须安装公司统一配发的杀毒软件和终端安全管理系统。
第十条 IT部门每季度对全公司IT设备进行巡检和维护。

第五章 设备报废与归还
第十一条 员工离职时必须归还所有IT设备，包括电脑、显示器、键盘鼠标等。IT部门检查设备完好性后办理归还手续。
第十二条 设备达到使用年限（电脑5年、其他设备3年）或无法修复的，由IT部门统一回收并报废处理。
""",
    },
    {
        "title": "绩效考核管理办法",
        "source_type": "text",
        "content": """公司绩效考核管理办法
第一章 总则
第一条 为建立科学规范的绩效管理体系，客观评价员工工作表现，激励员工提升工作绩效，特制定本办法。

第二章 考核周期与对象
第二条 绩效考核分为季度考核和年度考核。季度考核每季度末进行，年度考核在次年1月进行。
第三条 本办法适用于公司全体正式员工。试用期员工考核按照试用期管理规定执行。

第三章 考核内容与权重
第四条 绩效考核内容包括工作业绩（60%）、工作态度（20%）、能力素质（20%）三个维度。
第五条 工作业绩指标由员工直接上级与员工在季度初共同制定，须符合SMART原则（具体、可衡量、可达成、相关、有时限）。
第六条 工作态度维度主要考核责任心、团队协作、主动性、纪律性。
第七条 能力素质维度主要考核专业技能、学习能力、沟通能力、创新能力。

第四章 考核等级与分布
第八条 绩效考核结果分为S（优秀）、A（良好）、B（合格）、C（待改进）、D（不合格）五个等级。
第九条 考核等级实行强制分布：S级不超过总人数的10%，A级不超过20%，B级约占60%，C级和D级合计不低于10%。
第十条 S级员工当季绩效奖金系数为1.5，A级为1.2，B级为1.0，C级为0.5，D级为0。

第五章 考核结果应用
第十一条 绩效考核结果作为员工薪酬调整、晋升、培训、评优的重要依据。
第十二条 连续两个季度考核为D级的员工，公司有权解除劳动合同。
第十三条 年度考核为S级的员工，优先获得晋升资格和调薪机会。
""",
    },
]


# ── 多主题测试查询 ──────────────────────────────────────────────
QUERIES = [
    # 应命中"请假制度"
    ("年假有多少天", "请假"),
    ("结婚能休多久假", "请假"),
    ("女人生孩子产假多长时间", "请假"),
    # 应命中"差旅报销"
    ("出差住宿标准是多少", "差旅"),
    ("出差伙食补助每天多少钱", "差旅"),
    ("飞机票能不能报销", "差旅"),
    # 应命中"IT设备"
    ("开发岗位电脑配置是什么", "IT设备"),
    ("离职时电脑要还吗", "IT设备"),
    # 应命中"绩效考核"
    ("绩效考核等级有哪些", "绩效"),
    ("连续两个季度不合格会怎样", "绩效"),
    # 不相关查询（应被阈值过滤或得分很低）
    ("附近有什么好吃的", "无关"),
    ("今天天气怎么样", "无关"),
]


async def main() -> None:
    settings = get_settings()

    # 平台级上下文（tenant_id=None）
    ctx = RequestContext(
        scope="platform",
        tenant=None,
        host="platform.localhost",
        resolution="default",
    )

    print("=" * 60)
    print("第一步：上传多主题测试文档并执行 ingest")
    print("=" * 60)

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
            print(f"\n[创建] {doc['title']} → id={created.id}")

            chunk_count = await ing_service.ingest(
                document_id=created.id,
                raw_text=doc["content"],
                chunk_size=settings.rag_chunk_size,
                chunk_overlap=settings.rag_chunk_overlap,
            )
            print(f"[Ingest] {doc['title']} → {chunk_count} chunks")
        finally:
            uow.close()

    print("\n" + "=" * 60)
    print(f"第二步：多主题检索测试（阈值 = {settings.rag_similarity_threshold}）")
    print("=" * 60)

    uow = SqlAlchemyUnitOfWork(tenant_id=None)
    try:
        retrieval = RetrievalService(uow, ctx)

        for query, expected_topic in QUERIES:
            result = await retrieval.search(
                query=query,
                top_k=settings.rag_top_k,
                similarity_threshold=settings.rag_similarity_threshold,
            )

            if not result.chunks:
                status = "❌ 被阈值过滤"
                top_score = 0.0
            else:
                top = result.chunks[0]
                top_score = top.score
                status = "✅ 命中"

            print(
                f"\n查询: 「{query}」(期望: {expected_topic})"
                f"\n  最高分: {top_score:.4f}  状态: {status}  命中数: {len(result.chunks)}"
            )
            for i, c in enumerate(result.chunks[:3]):
                preview = c.content[:80].replace("\n", " ")
                print(f"  [{i + 1}] score={c.score:.4f}  {preview}...")
    finally:
        uow.close()


if __name__ == "__main__":
    asyncio.run(main())
