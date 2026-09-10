# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/zujuan/_progress.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
知识点采集进度的读写（见 docs/zujuan/知识点切片抓取规范.md 第 5 节）。

两条纪律：

1. ``knowledge_tree`` 是共享表，树结构那一组列归"知识点树同步"那条线。这里
   所有写入都过 :data:`TREE_PROGRESS_COLUMNS` 白名单，出现结构列直接抛错 ——
   和 ``questions`` 表用"ORM 不声明"来兜底是同一个思路，只是这张表必须能读
   结构列，所以改成白名单校验。
2. ``collected`` 必须**重算**，不能每采一道 +1。采集是可以重跑的，累加会一直
   膨胀；而且一道题挂多个知识点，加法根本对不上。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import case, func, insert, or_, select, update

from database.db_session import get_session
from database.models import (
    ZujuanKnowledgeSlice,
    ZujuanKnowledgeTree,
    ZujuanQuestion as ZujuanQuestionOrm,
    ZujuanQuestionKnowledge,
)
from media_platform.zujuan import slicing
from tools import utils

# scrape_status 的取值，knowledge_tree 和 knowledge_slice 共用同一套
STATUS_NONE = "none"
STATUS_PARTIAL = "partial"
STATUS_SLICING = "slicing"
STATUS_DONE = "done"
STATUS_CAPPED = "capped"
STATUS_EMPTY = "empty"

# 已经处理完、这次不用再碰的终止状态
TERMINAL_STATUS = frozenset({STATUS_DONE, STATUS_CAPPED, STATUS_EMPTY})

# 还能接着采的状态，挑待办知识点时用
PENDING_STATUS = (STATUS_NONE, STATUS_PARTIAL, STATUS_SLICING)

# ★ knowledge_tree 上本项目唯一允许写的列。多写一列就会把"知识点树同步"
#   那条线的产物冲掉
TREE_PROGRESS_COLUMNS = frozenset(
    {
        "is_leaf",
        "scrape_status",
        "site_total",
        "collected",
        "last_page",
        "covered_pages",
        "scraped_at",
        "note",
    }
)

# knowledge_slice 整张表都是本项目的，除了两列主键都能写
SLICE_COLUMNS = frozenset(
    {
        "dim",
        "slice_name",
        "depth",
        "scrape_status",
        "site_total",
        "collected",
        "last_page",
        "covered_pages",
        "scraped_at",
        "note",
    }
)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


@dataclass
class KnowledgeTarget:
    """一个待抓的知识点（一定是叶子）"""

    knowledge_id: str
    title: Optional[str] = None
    path: Optional[str] = None
    bank_id: Optional[str] = None
    scrape_status: str = STATUS_NONE
    site_total: Optional[int] = None
    last_page: int = 0
    covered_pages: Optional[str] = None

    @property
    def resume_page(self) -> int:
        return slicing.first_uncovered_page(self.covered_pages, self.last_page)


@dataclass
class SliceProgress:
    """knowledge_slice 里的一行"""

    knowledge_id: str
    slice_key: str
    scrape_status: str = STATUS_NONE
    site_total: Optional[int] = None
    last_page: int = 0
    covered_pages: Optional[str] = None

    @property
    def resume_page(self) -> int:
        return slicing.first_uncovered_page(self.covered_pages, self.last_page)


def _reject_foreign_columns(fields: Dict[str, Any], allowed: frozenset, table: str) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(
            f"[zujuan._progress] 拒绝写 {table} 的 {sorted(unknown)} 列："
            f"本项目只负责 {sorted(allowed)}，写别的列会覆盖其它阶段的产物"
        )


async def fetch_leaf_targets(
    limit: int = 0,
    knowledge_ids: Optional[Sequence[str]] = None,
    bank_id: Optional[str] = None,
    only_uncrawled: bool = False,
    exclude_path_keywords: Optional[Sequence[str]] = None,
) -> List[KnowledgeTarget]:
    """挑出这次要抓的叶子知识点。

    ★ 只挑叶子（``child_count == 0``）：父节点的列表页包含它全部子孙的题，
      采父节点等于把子节点的题重复翻一遍。

    ``only_uncrawled`` 只挑从来没跑过的（``scrape_status='none'``），浅采铺底用。
    ``exclude_path_keywords`` 按 ``path`` 里的关键字排掉整个分支。

    ★ 两个过滤都下推到 SQL，不能取回来再在 Python 里筛 —— ``limit`` 是在数据库
      侧生效的，先 limit 后筛会让 ``--knowledge_limit 50`` 实际拿到不足 50 个。
    """
    tree = ZujuanKnowledgeTree
    stmt = select(
        tree.knowledge_id,
        tree.title,
        tree.path,
        tree.bank_id,
        tree.scrape_status,
        tree.site_total,
        tree.last_page,
        tree.covered_pages,
    ).where(tree.child_count == 0)

    if knowledge_ids:
        # 手动指定时不看状态，让人能重跑任意一个知识点
        stmt = stmt.where(tree.knowledge_id.in_(list(knowledge_ids)))
    else:
        if only_uncrawled:
            stmt = stmt.where(tree.scrape_status == STATUS_NONE)
        else:
            stmt = stmt.where(tree.scrape_status.in_(PENDING_STATUS))
        if bank_id:
            stmt = stmt.where(tree.bank_id == str(bank_id))

    for keyword in exclude_path_keywords or ():
        keyword = (keyword or "").strip()
        if keyword:
            # path 为空的节点不该被排除条件顺手滤掉，所以显式放行 NULL
            stmt = stmt.where(
                or_(tree.path.is_(None), tree.path.notlike(f"%{keyword}%"))
            )

    # 半路停下的排在最前面：它们已经翻过一部分，先收尾比新开一个更划算
    priority = case(
        (tree.scrape_status == STATUS_PARTIAL, 0),
        (tree.scrape_status == STATUS_SLICING, 1),
        else_=2,
    )
    stmt = stmt.order_by(priority, tree.level, tree.sort_ord, tree.knowledge_id)
    if limit and limit > 0:
        stmt = stmt.limit(limit)

    async with get_session() as session:
        rows = (await session.execute(stmt)).all()

    return [
        KnowledgeTarget(
            knowledge_id=row.knowledge_id,
            title=row.title,
            path=row.path,
            bank_id=row.bank_id,
            scrape_status=row.scrape_status or STATUS_NONE,
            site_total=row.site_total,
            last_page=row.last_page or 0,
            covered_pages=row.covered_pages,
        )
        for row in rows
    ]


async def fetch_slice_map(knowledge_id: str) -> Dict[str, SliceProgress]:
    """一个知识点已有的全部切片进度，key 是 slice_key"""
    sl = ZujuanKnowledgeSlice
    stmt = select(
        sl.slice_key, sl.scrape_status, sl.site_total, sl.last_page, sl.covered_pages
    ).where(sl.knowledge_id == knowledge_id)
    async with get_session() as session:
        rows = (await session.execute(stmt)).all()
    return {
        row.slice_key: SliceProgress(
            knowledge_id=knowledge_id,
            slice_key=row.slice_key,
            scrape_status=row.scrape_status or STATUS_NONE,
            site_total=row.site_total,
            last_page=row.last_page or 0,
            covered_pages=row.covered_pages,
        )
        for row in rows
    }


async def save_tree_progress(knowledge_id: str, **fields: Any) -> None:
    """更新 knowledge_tree 的进度列。每页调用一次，立刻提交。"""
    _reject_foreign_columns(fields, TREE_PROGRESS_COLUMNS, "knowledge_tree")
    if not fields:
        return
    fields.setdefault("scraped_at", now_iso())
    async with get_session() as session:
        await session.execute(
            update(ZujuanKnowledgeTree)
            .where(ZujuanKnowledgeTree.knowledge_id == knowledge_id)
            .values(**fields)
        )


async def save_slice_progress(knowledge_id: str, slice_key: str, **fields: Any) -> None:
    """knowledge_slice 的 upsert：先查再决定插入还是更新"""
    _reject_foreign_columns(fields, SLICE_COLUMNS, "knowledge_slice")
    fields.setdefault("scraped_at", now_iso())
    sl = ZujuanKnowledgeSlice
    async with get_session() as session:
        existing = (
            await session.execute(
                select(sl.slice_key).where(
                    sl.knowledge_id == knowledge_id, sl.slice_key == slice_key
                )
            )
        ).first()
        if existing is None:
            await session.execute(
                insert(sl).values(knowledge_id=knowledge_id, slice_key=slice_key, **fields)
            )
        else:
            await session.execute(
                update(sl)
                .where(sl.knowledge_id == knowledge_id, sl.slice_key == slice_key)
                .values(**fields)
            )


def slice_conditions(parts: Dict[str, str]) -> List[Any]:
    """把筛选条件翻译成 questions 上的过滤条件，用来重算 collected"""
    question = ZujuanQuestionOrm
    conditions: List[Any] = []

    qtype_code = parts.get(slicing.DIM_QTYPE)
    if qtype_code:
        conditions.append(
            question.qtype_code == slicing.slice_value(slicing.DIM_QTYPE, qtype_code).db_value
        )

    difficulty_code = parts.get(slicing.DIM_DIFFICULTY)
    if difficulty_code:
        # ★ 站点的 d1/d2/d3 是 3 档，对应库里由得分率重算的 difficulty_band，
        #   不是按钮上那 5 档的 difficulty_code —— 两套编码数值会撞车
        conditions.append(
            question.difficulty_band
            == slicing.slice_value(slicing.DIM_DIFFICULTY, difficulty_code).db_value
        )

    sub_type_code = parts.get(slicing.DIM_SUB_TYPE)
    if sub_type_code:
        conditions.append(
            question.qtype_sub == slicing.slice_value(slicing.DIM_SUB_TYPE, sub_type_code).db_value
        )

    year_code = parts.get(slicing.DIM_YEAR)
    if year_code:
        raw = slicing.slice_value(slicing.DIM_YEAR, year_code).db_value
        if raw == "-1":
            conditions.append(question.year < slicing.EARLIEST_YEAR)
        else:
            conditions.append(question.year == int(raw))
    return conditions


async def recount_knowledge(knowledge_id: str) -> int:
    """重算一个知识点在库里的题数（只对叶子有意义，父节点站点一道都不标）"""
    stmt = (
        select(func.count())
        .select_from(ZujuanQuestionKnowledge)
        .where(ZujuanQuestionKnowledge.knowledge_id == knowledge_id)
    )
    async with get_session() as session:
        return int((await session.execute(stmt)).scalar() or 0)


async def recount_slice(knowledge_id: str, slice_key: str) -> int:
    """重算一片在库里的题数"""
    conditions = slice_conditions(slicing.parse_slice_key(slice_key))
    stmt = (
        select(func.count())
        .select_from(ZujuanQuestionKnowledge)
        .join(
            ZujuanQuestionOrm,
            ZujuanQuestionOrm.question_id == ZujuanQuestionKnowledge.question_id,
        )
        .where(ZujuanQuestionKnowledge.knowledge_id == knowledge_id, *conditions)
    )
    async with get_session() as session:
        return int((await session.execute(stmt)).scalar() or 0)


async def refresh_collected(knowledge_id: str) -> Optional[int]:
    """重算并回写一个知识点的 collected，失败只告警不打断采集"""
    try:
        total = await recount_knowledge(knowledge_id)
    except Exception as e:  # noqa: BLE001 - 统计失败不能影响已经采到的数据
        utils.logger.warning(f"[zujuan._progress] {knowledge_id} collected 重算失败: {e}")
        return None
    await save_tree_progress(knowledge_id, collected=total)
    return total


async def refresh_slice_collected(knowledge_id: str, slice_key: str) -> Optional[int]:
    try:
        total = await recount_slice(knowledge_id, slice_key)
    except Exception as e:  # noqa: BLE001
        utils.logger.warning(
            f"[zujuan._progress] {knowledge_id}/{slice_key} collected 重算失败: {e}"
        )
        return None
    await save_slice_progress(knowledge_id, slice_key, collected=total)
    return total
