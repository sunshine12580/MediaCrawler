# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/zujuan_reset_false_done.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
把被误标成 done 的组卷网知识点/分片打回未完成状态。

背景：`_page_through()` 早先把"这一页没有题目卡片"无条件当成"翻到底了"。
网慢的时候页面还没渲染完就被读走，拿到的是一个"有 #questioncount、零张卡片"的
半成品，于是一个才翻了 8 页的知识点被记成 done —— 剩下的题再也不会被采集，
而且不报错。线上 zsd6026（site_total=656 共 66 页，停在第 8 页）就是这么来的。

判据用 `slicing.is_fully_covered()`，和采集时的完成判定完全一致：
"该翻的页都翻过了"而不是"库里的数够了"。超过翻页硬顶的行也一并打回，它们
本来就不可能靠翻页覆盖完，该走切片。

默认只看不改，加 --apply 才写库。
"""

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

try:  # Windows 控制台默认 GBK，知识点名里的字符会直接把脚本打崩
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import config
from media_platform.zujuan import slicing
from store.zujuan import _progress as progress
from tools import utils


@dataclass
class Row:
    knowledge_id: str
    title: str
    slice_key: str  # 空串表示 knowledge_tree 那一行
    site_total: Optional[int]
    last_page: int
    covered_pages: str
    reason: str

    @property
    def label(self) -> str:
        return f"{self.knowledge_id}/{self.slice_key}" if self.slice_key else self.knowledge_id


def _has_children(knowledge_id: str, slice_key: str, all_keys: Dict[str, set]) -> bool:
    """这一片有没有被再往下切过。子片的 key 是父片 key 加后缀（t4 -> t4d1 -> t4d1s5）"""
    keys = all_keys.get(knowledge_id, set())
    return any(other != slice_key and other.startswith(slice_key) for other in keys)


def _reason(site_total: Optional[int], covered: str, last_page: int) -> Optional[str]:
    """这一行为什么不该是 done，已经采完就返回 None。

    ★ 判据必须和采集时的续采起点用同一个函数 `first_uncovered_page(covered, last_page)`
      —— covered_pages 是后来才加的列，老数据那一列是空的但 last_page 有值。
      只看 covered_pages 会把几十个其实已经采完的知识点全判成"第 1 页起没翻过"，
      白白重采一遍。
    """
    if site_total is None:
        return "site_total 未知，无法判定采完"
    if site_total <= 0:
        return None  # 站点说没题，该是 empty 不是 done，交给人看，别在这里改
    if slicing.exceeds_hard_cap(site_total):
        return f"共 {site_total} 道超过翻页硬顶 {slicing.HARD_CAP}，翻页覆盖不完，应走切片"
    should = slicing.total_pages(site_total)
    first_gap = slicing.first_uncovered_page(covered, last_page)
    if first_gap <= should:
        return f"站点共 {site_total} 道 = {should} 页，只翻到第 {first_gap - 1} 页"
    return None


async def _collect() -> Dict[str, List[Row]]:
    from sqlalchemy import select

    from database.models import ZujuanKnowledgeSlice, ZujuanKnowledgeTree
    from database.db_session import get_session

    tree, sl = ZujuanKnowledgeTree, ZujuanKnowledgeSlice
    async with get_session() as session:
        tree_rows = (
            await session.execute(
                select(
                    tree.knowledge_id, tree.title, tree.site_total,
                    tree.last_page, tree.covered_pages,
                ).where(tree.child_count == 0, tree.scrape_status == progress.STATUS_DONE)
            )
        ).all()
        slice_rows = (
            await session.execute(
                select(
                    sl.knowledge_id, sl.slice_key, sl.site_total,
                    sl.last_page, sl.covered_pages,
                ).where(sl.scrape_status == progress.STATUS_DONE)
            )
        ).all()
        all_slice_keys = {}
        for kid, key in (await session.execute(select(sl.knowledge_id, sl.slice_key))).all():
            all_slice_keys.setdefault(kid, set()).add(key)

        # 有分片的知识点，题是分片采的，树那一行的 covered_pages 本来就是空的，
        # 不能拿它判"没翻过页" —— 那会把一批采好的知识点全打回去重采
        sliced_ids = {
            row[0]
            for row in (await session.execute(select(sl.knowledge_id).distinct())).all()
        }
        titles = dict(
            (row[0], row[1])
            for row in (await session.execute(select(tree.knowledge_id, tree.title))).all()
        )

    bad_tree: List[Row] = []
    for kid, title, site_total, last_page, covered in tree_rows:
        if kid in sliced_ids:
            continue
        reason = _reason(site_total, covered or "", last_page or 0)
        if reason:
            bad_tree.append(Row(kid, title or "", "", site_total, last_page or 0, covered or "", reason))

    bad_slice: List[Row] = []
    for kid, key, site_total, last_page, covered in slice_rows:
        if _has_children(kid, key, all_slice_keys):
            # ★ 被再往下切过的父片：它自己没翻过页（last_page=0、题数超硬顶），
            #   done 是子片全部采完之后汇总上来的，本来就该是这样，不是误标
            continue
        reason = _reason(site_total, covered or "", last_page or 0)
        if reason:
            bad_slice.append(
                Row(kid, titles.get(kid, ""), key, site_total, last_page or 0, covered or "", reason)
            )
    return {"tree": bad_tree, "slice": bad_slice}


async def main(apply: bool) -> int:
    config.SAVE_DATA_OPTION = "db"
    found = await _collect()
    bad_tree, bad_slice = found["tree"], found["slice"]

    for row in bad_tree:
        print(f"[tree ] {row.label:<12} {row.title[:28]:<30} last_page={row.last_page:<5} {row.reason}")
    for row in bad_slice:
        print(f"[slice] {row.label:<24} last_page={row.last_page:<5} {row.reason}")

    # 分片被打回的知识点，树那一行也得从终态放出来，否则下一轮根本不会选到它
    parents = sorted({row.knowledge_id for row in bad_slice})
    print(f"\n知识点 {len(bad_tree)} 个 / 分片 {len(bad_slice)} 片"
          f" / 需要一并放开的父知识点 {len(parents)} 个")

    if not apply:
        print("\n（只看不改。确认无误后加 --apply 才会写库）")
        return 0

    note = "空页误判修复：被误标 done，已打回重采"
    for row in bad_tree:
        await progress.save_tree_progress(
            row.knowledge_id, scrape_status=progress.STATUS_PARTIAL, note=note
        )
    for row in bad_slice:
        await progress.save_slice_progress(
            row.knowledge_id, row.slice_key,
            scrape_status=progress.STATUS_PARTIAL, note=note,
        )
    for kid in parents:
        await progress.save_tree_progress(
            kid, scrape_status=progress.STATUS_SLICING, note=note
        )
    print(f"\n已写库：{len(bad_tree)} 个知识点 + {len(bad_slice)} 片 -> partial，"
          f"{len(parents)} 个父知识点 -> slicing")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真的写库；不加就只打印")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.apply)))
