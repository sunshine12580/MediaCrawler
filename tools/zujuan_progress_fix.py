# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/zujuan_progress_fix.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
一次性修正 knowledge_tree / knowledge_slice 的进度列。默认只干跑不写库。

做三件事：

1. **covered_pages 换格式** —— 老数据是区间压缩（``1-281``），改成逐页逗号分隔
   （``1,2,3,…``）。区间格式看不出中间缺没缺页，补采时得先在脑子里展开。
2. **补写漏掉的 done** —— watch 模式早期版本没有完成判定，一直只写 partial。
   凡是页码已经覆盖满（``ceil(site_total/10)`` 页都采过）的行，状态补成 done。
3. **重算 collected** —— 顺带把这些行的入库量重算一遍（重算不是累加）。

只碰这三列，树结构和其它阶段的产物一列都不动。

用法：
    uv run python tools/zujuan_progress_fix.py            # 干跑，只打印会改什么
    uv run python tools/zujuan_progress_fix.py --apply    # 真正写库
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import config  # noqa: E402
from media_platform.zujuan import slicing  # noqa: E402


def preview(value: str, width: int = 56) -> str:
    return value if len(value) <= width else value[:width] + "…"


async def collect_changes():
    from sqlalchemy import select

    from database.db_session import get_session
    from database.models import ZujuanKnowledgeSlice, ZujuanKnowledgeTree

    changes = []
    async with get_session() as session:
        tree = ZujuanKnowledgeTree
        rows = (
            await session.execute(
                select(
                    tree.knowledge_id, tree.title, tree.covered_pages,
                    tree.site_total, tree.scrape_status,
                ).where(tree.child_count == 0)
            )
        ).all()
        for row in rows:
            change = build_change(
                "knowledge_tree", row.knowledge_id, "", row.title,
                row.covered_pages, row.site_total, row.scrape_status,
            )
            if change:
                changes.append(change)

        sl = ZujuanKnowledgeSlice
        rows = (
            await session.execute(
                select(
                    sl.knowledge_id, sl.slice_key, sl.slice_name,
                    sl.covered_pages, sl.site_total, sl.scrape_status,
                )
            )
        ).all()
        for row in rows:
            change = build_change(
                "knowledge_slice", row.knowledge_id, row.slice_key, row.slice_name,
                row.covered_pages, row.site_total, row.scrape_status,
            )
            if change:
                changes.append(change)
    return changes


def build_change(table, knowledge_id, slice_key, title, covered, site_total, status):
    fields = {}
    if covered:
        normalized = slicing.format_covered_pages(slicing.parse_page_ranges(covered))
        if normalized != covered:
            fields["covered_pages"] = normalized
        covered = normalized

    finished = slicing.is_fully_covered(covered, site_total)
    if finished and status not in ("done", "capped", "empty"):
        fields["scrape_status"] = "done"

    if not fields:
        return None
    return {
        "table": table,
        "knowledge_id": knowledge_id,
        "slice_key": slice_key,
        "title": title,
        "old_covered": covered,
        "site_total": site_total,
        "old_status": status,
        "fields": fields,
        "missing": slicing.missing_pages(covered, site_total),
    }


async def apply_changes(changes):
    from sqlalchemy import update

    from database.db_session import get_session
    from database.models import ZujuanKnowledgeSlice, ZujuanKnowledgeTree
    from store.zujuan import _progress as progress

    for change in changes:
        if change["table"] == "knowledge_tree":
            stmt = (
                update(ZujuanKnowledgeTree)
                .where(ZujuanKnowledgeTree.knowledge_id == change["knowledge_id"])
                .values(**change["fields"])
            )
        else:
            stmt = (
                update(ZujuanKnowledgeSlice)
                .where(
                    ZujuanKnowledgeSlice.knowledge_id == change["knowledge_id"],
                    ZujuanKnowledgeSlice.slice_key == change["slice_key"],
                )
                .values(**change["fields"])
            )
        async with get_session() as session:
            await session.execute(stmt)

        # 顺带把入库量重算一遍（重算不是累加）
        if change["table"] == "knowledge_tree":
            await progress.refresh_collected(change["knowledge_id"])
        else:
            await progress.refresh_slice_collected(
                change["knowledge_id"], change["slice_key"]
            )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写库；不加就只干跑")
    args = parser.parse_args()

    config.SAVE_DATA_OPTION = "db"
    changes = await collect_changes()
    if not changes:
        print("没有需要修正的行。")
        return

    reformat = sum(1 for c in changes if "covered_pages" in c["fields"])
    restatus = sum(1 for c in changes if "scrape_status" in c["fields"])
    print(f"共 {len(changes)} 行需要修正：换格式 {reformat} 行，补写 done {restatus} 行\n")

    for change in changes:
        label = change["knowledge_id"] + (
            "/" + change["slice_key"] if change["slice_key"] else ""
        )
        marks = []
        if "covered_pages" in change["fields"]:
            marks.append("换格式")
        if "scrape_status" in change["fields"]:
            marks.append(f"{change['old_status']} -> done")
        print(f"  {label:<22} {(change['title'] or '')[:20]:<22} {' / '.join(marks)}")
        if "covered_pages" in change["fields"]:
            print(f"     covered_pages: {preview(change['fields']['covered_pages'])}")
        print(
            f"     site_total={change['site_total']} 还缺 {len(change['missing'])} 页"
        )

    if not args.apply:
        print("\n以上是干跑结果，一行都没写。确认无误后加 --apply 真正执行。")
        return

    await apply_changes(changes)
    print(f"\n已写入 {len(changes)} 行，并重算了这些行的 collected。")


if __name__ == "__main__":
    asyncio.run(main())
