"""验证 markdown 切分。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from internal.domain.retrieval.text_split import split_markdown

md = """# 公司请假制度

## 第一章 总则

为规范公司请假管理，保障员工合法权益，特制定本制度。本制度适用于公司全体正式员工、试用期员工及实习生。

## 第二章 各类假期规定

### 第三条 年假

员工累计工作已满1年不满10年的，年休假5天；已满10年不满20年的，年休假10天；已满20年的，年休假15天。

### 第四条 病假

员工因病需要休假的，应提供二级以上医院出具的病假证明。病假期间工资按当地最低工资标准的80%发放。

### 第五条 婚假

员工达到法定结婚年龄结婚的，可享受3天婚假。晚婚增加15天婚假。
"""

chunks = split_markdown(md, chunk_size=200, chunk_overlap=30)
for i, c in enumerate(chunks):
    print(f"--- chunk {i} heading_path={c.heading_path}")
    print(c.content[:200])
