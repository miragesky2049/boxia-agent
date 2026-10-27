"""HR 字典默认项种子：迁移 0019 与租户初始化共用同一份清单。"""

# (category, code, name, sort_order)
DEFAULT_HR_DICTIONARY_ITEMS: tuple[tuple[str, str, str, int], ...] = (
    # 雇佣类型
    ("employment_type", "full_time", "全职", 10),
    ("employment_type", "part_time", "兼职", 20),
    ("employment_type", "intern", "实习", 30),
    ("employment_type", "outsourced", "外包", 40),
    ("employment_type", "dispatched", "派遣", 50),
    ("employment_type", "consultant", "顾问", 60),
    # 岗位职级（技术与管理双通道）
    ("job_level", "P1", "P1", 10),
    ("job_level", "P2", "P2", 20),
    ("job_level", "P3", "P3", 30),
    ("job_level", "P4", "P4", 40),
    ("job_level", "P5", "P5", 50),
    ("job_level", "P6", "P6", 60),
    ("job_level", "P7", "P7", 70),
    ("job_level", "M1", "M1", 100),
    ("job_level", "M2", "M2", 110),
    ("job_level", "M3", "M3", 120),
    ("job_level", "M4", "M4", 130),
    # 岗位序列
    ("job_family", "tech", "技术", 10),
    ("job_family", "product", "产品", 20),
    ("job_family", "design", "设计", 30),
    ("job_family", "operation", "运营", 40),
    ("job_family", "sales", "销售", 50),
    ("job_family", "marketing", "市场", 60),
    ("job_family", "function", "职能", 70),
)
