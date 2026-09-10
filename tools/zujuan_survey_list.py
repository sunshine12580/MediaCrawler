# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/zujuan_survey_list.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
生成"待摸底知识点"的可点清单（只读数据库，不碰站点）。

用途：knowledge_tree 里 site_total 为空的知识点，站点上到底有多少道题是未知的，
没有这个数就没法判断还差多少、值不值得继续采。这个脚本把这些知识点排好序输出成
一个 HTML 清单，你在浏览器里挨个点开首页；watch 模式会自动把每页上的
"共计 N 道试题" 写进 knowledge_tree.site_total。

排序按"库里已有的题次"从多到少 —— 已有越多的知识点，潜在缺口的绝对值越大，
先摸这些最快看出全局缺口。

用法：
    uv run python tools/zujuan_survey_list.py            # 全部
    uv run python tools/zujuan_survey_list.py --limit 50 # 只出前 50 个
"""

import argparse
import asyncio
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台默认 GBK，知识点名字里有它编不出来的字符就会整个脚本崩掉
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 老 Python / 非标准 stdout 时忽略
    pass

import config  # noqa: E402
from media_platform.zujuan import slicing  # noqa: E402

OUTPUT = os.path.join("data", "zujuan_survey.html")


async def fetch_rows(limit: int):
    from sqlalchemy import func, select

    from database.db_session import get_session
    from database.models import ZujuanKnowledgeTree, ZujuanQuestionKnowledge

    tree = ZujuanKnowledgeTree
    counts = (
        select(
            ZujuanQuestionKnowledge.knowledge_id.label("kid"),
            func.count().label("c"),
        )
        .group_by(ZujuanQuestionKnowledge.knowledge_id)
        .subquery()
    )
    stmt = (
        select(tree.knowledge_id, tree.title, tree.path, func.coalesce(counts.c.c, 0))
        .outerjoin(counts, counts.c.kid == tree.knowledge_id)
        .where(tree.child_count == 0, tree.site_total.is_(None))
        .order_by(func.coalesce(counts.c.c, 0).desc(), tree.knowledge_id)
    )
    if limit:
        stmt = stmt.limit(limit)
    async with get_session() as session:
        return (await session.execute(stmt)).all()


def render(rows, prefix: str) -> str:
    parts = [
        "<meta charset='utf-8'><title>组卷网知识点摸底清单</title>",
        "<style>body{font:14px/1.7 system-ui,sans-serif;margin:24px;max-width:1000px}"
        "h1{font-size:20px}ol{padding-left:28px}li{margin:2px 0}"
        "a{text-decoration:none}a:visited{color:#888}"  # 点过的变灰，一眼看出进度
        ".n{color:#888;font-size:12px;margin-left:8px}"
        ".p{color:#aaa;font-size:12px}</style>",
        f"<h1>待摸底知识点（{len(rows)} 个）</h1>",
        "<p>先启动 watch 模式，再从上往下逐个点开。每打开一个，"
        "脚本就把页面上的“共计 N 道试题”写进 <code>knowledge_tree.site_total</code>。"
        "<b>只要打开首页即可，不用翻页。</b>点过的链接会变灰。</p>",
        "<p class=p>排序：按库里已有题次从多到少 —— 已有越多，潜在缺口的绝对值越大。</p>",
        "<ol>",
    ]
    for knowledge_id, title, path, have in rows:
        url = slicing.build_list_url(knowledge_id, {}, prefix=prefix)
        parts.append(
            f"<li><a href='{html.escape(url)}' target='_blank'>"
            f"{html.escape(title or knowledge_id)}</a>"
            f"<span class=n>{knowledge_id} · 库里已有 {have:,}</span></li>"
        )
    parts.append("</ol>")
    return "\n".join(parts)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只出前 N 个，0 表示全部")
    args = parser.parse_args()

    config.SAVE_DATA_OPTION = "db"
    rows = await fetch_rows(args.limit)
    if not rows:
        print("没有待摸底的知识点 —— knowledge_tree 里叶子节点的 site_total 都有值了")
        return

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(rows, getattr(config, "ZUJUAN_URL_PREFIX", "czsx")))

    print(f"共 {len(rows)} 个待摸底知识点，清单已写入: {OUTPUT}")
    print("用法：先跑 watch 模式，再在浏览器里打开这个文件，从上往下点。")
    print("\n前 10 个：")
    for knowledge_id, title, _, have in rows[:10]:
        print(f"  {knowledge_id:<12} {(title or '')[:26]:<28} 库里已有 {have:>7,}")


if __name__ == "__main__":
    asyncio.run(main())
