# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/zujuan/_store_impl.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网存储实现

写入规则见 docs/zujuan/题干入库规范.md。三条不能破的纪律：

1. questions 是多阶段共享的大表 —— **只 SET 本次解析出的非空列**。多 SET 一列
   （哪怕设成 NULL）就会把 answer_img / stem_md / render_status 这些其它阶段
   已经写好的产物冲掉，这是唯一一条做错了会造成不可逆数据损失的规则。
   本模块靠两层保证：ORM 只声明了抓取阶段负责的 35 列，且 build_question_row()
   会丢掉所有空值。
2. 库里已有且 stem_hash 非空 -> 整题跳过，关联表也不动。
3. questions 的写入 + 两张关联表的先删后插，必须在同一个事务里提交。
"""

import json
import os
import re
import socket
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiofiles
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

import config
from base.base_crawler import AbstractStore
from database.db_session import get_session
from database.models import (
    ZujuanQuestion as ZujuanQuestionOrm,
    ZujuanQuestionKnowledge,
    ZujuanQuestionSource,
)
from model.m_zujuan import ZujuanQuestion
from tools import utils
from tools.async_file_writer import AsyncFileWriter
from var import crawler_type_var

# questions 表里本次任务负责写的列。模型字段同名，逐列对应。
# ★ 这个清单之外的列一律不碰，尤其是 stem_text / stem_md / answer_* / render_status
QUESTION_COLUMNS = (
    "question_id", "grade", "bank_id",
    "stem_html", "stem_status", "stem_hash",
    "qtype", "qtype_code", "qtype_full", "qtype_sub",
    "difficulty", "difficulty_code", "difficulty_band", "score_rate",
    "source", "title_abbr", "category_id", "category_name",
    "school_year", "year", "grade_level", "term",
    "province", "province_code", "city", "source_type",
    "paper_id", "used_count", "is_famous_school", "is_real_exam",
    "list_url", "knowledge_id", "knowledge_tags", "raw_day",
)


def build_question_row(question: ZujuanQuestion) -> Dict[str, Any]:
    """
    模型 -> {列名: 值}，**丢掉所有空值**。

    只丢 None 和空串：0 必须留下 —— is_famous_school=0 是"确认没有名校角标"，
    used_count=0 是真的没被组过卷，都不是"没解析到"。
    """
    row: Dict[str, Any] = {}
    for column in QUESTION_COLUMNS:
        value = getattr(question, column, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        row[column] = value
    return row


def now_iso() -> str:
    """和库里已有数据同格式：2026-08-25T22:35:25"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def dedup_knowledge(question: ZujuanQuestion) -> List[Dict[str, Any]]:
    """
    知识点去重后转成关联表行。

    卡片末尾的"能力标签"（href 形如 /czsx/zsd5249/tre5-15091）抠出来的 id 会和
    前面的知识点撞车，而 question_knowledge 的主键是 (question_id, knowledge_id)，
    不去重就会主键冲突。保留先出现的那条，ord 去重后重新连续编号。
    原始那份含重复的数组照旧进 JSONL 和 knowledge_tags。
    """
    rows: List[Dict[str, Any]] = []
    seen = set()
    for item in question.knowledge:
        if not item.id or item.id in seen:
            continue
        seen.add(item.id)
        rows.append({
            "question_id": question.question_id,
            "knowledge_id": item.id,
            "knowledge_name": item.name or None,
            "ord": len(rows),
        })
    return rows


def dedup_sources(question: ZujuanQuestion) -> List[Dict[str, Any]]:
    """来源试卷去重后转成关联表行，规则同上"""
    rows: List[Dict[str, Any]] = []
    seen = set()
    for item in question.sources:
        if not item.paper_id or item.paper_id in seen:
            continue
        seen.add(item.paper_id)
        rows.append({
            "question_id": question.question_id,
            "paper_id": item.paper_id,
            "paper_title": item.title or None,
            "ord": len(rows),
        })
    return rows


class ZuJuanDbStoreImplement(AbstractStore):
    """写 questions + question_knowledge + question_sources 三张表"""

    async def store_content(self, content_item: ZujuanQuestion):
        question = content_item
        if not question.question_id:
            # 没有 ID 的卡片不入库，调用方已经单独告警过了
            return

        async with get_session() as session:
            existing = (
                await session.execute(
                    select(ZujuanQuestionOrm.question_id, ZujuanQuestionOrm.stem_hash).where(
                        ZujuanQuestionOrm.question_id == question.question_id
                    )
                )
            ).first()

            if (
                existing is not None
                and existing.stem_hash
                and getattr(config, "ZUJUAN_SKIP_EXISTING", True)
            ):
                # 已经有可用的题干，这道题这次什么都不写
                utils.logger.debug(
                    f"[ZuJuanDbStore] question_id {question.question_id} 已存在且题干非空，跳过"
                )
                return

            row = build_question_row(question)
            if existing is None:
                row["first_seen_at"] = now_iso()
                try:
                    await session.execute(insert(ZujuanQuestionOrm).values(**row))
                except IntegrityError:
                    # 并发下另一个进程刚插进去，当作已存在走更新分支
                    await session.rollback()
                    row.pop("first_seen_at", None)
                    await session.execute(
                        update(ZujuanQuestionOrm)
                        .where(ZujuanQuestionOrm.question_id == question.question_id)
                        .values(**row)
                    )
            else:
                # ★ first_seen_at 只在第一次插入时写，任何更新都不许改它
                row.pop("first_seen_at", None)
                await session.execute(
                    update(ZujuanQuestionOrm)
                    .where(ZujuanQuestionOrm.question_id == question.question_id)
                    .values(**row)
                )

            await self._replace_relations(session, question)

    @staticmethod
    async def _replace_relations(session, question: ZujuanQuestion) -> None:
        """
        两张关联表先删后插。

        内容完全由这一次解析结果决定，不存在"库里有一条但这次没抓到，要不要保留"
        的判断需求，先删后插最简单也不会留残渣。
        """
        question_id = question.question_id

        await session.execute(
            delete(ZujuanQuestionKnowledge).where(ZujuanQuestionKnowledge.question_id == question_id)
        )
        knowledge_rows = dedup_knowledge(question)
        if knowledge_rows:
            await session.execute(insert(ZujuanQuestionKnowledge), knowledge_rows)

        await session.execute(
            delete(ZujuanQuestionSource).where(ZujuanQuestionSource.question_id == question_id)
        )
        source_rows = dedup_sources(question)
        if source_rows:
            await session.execute(insert(ZujuanQuestionSource), source_rows)

    async def store_comment(self, comment_item: Dict):
        """组卷网列表页没有评论维度"""

    async def store_creator(self, creator: Dict):
        """本项目不采集任何用户信息"""


class ZuJuanSqliteStoreImplement(ZuJuanDbStoreImplement):
    """SQLite 与 MySQL 共用同一套 SQLAlchemy 实现"""


_NODE_ID_UNSAFE_RE = re.compile(r"[^a-z0-9_.-]+")


def resolve_node_id() -> str:
    """本节点的标识，拼进原始 JSONL 的文件名：<日期>-<节点>-n<序号>.jsonl

    多台机器同时跑时，各自的 data/raw/ 都从 n1 开始写，不带节点的话文件名一模一样；
    questions.raw_day 是 varchar(10) 只装得下日期，库里看不出某道题的原始卡片在哪台
    机器上。日后把几台的快照合到一个目录，同名文件会直接互相覆盖 —— 而这是卡片原文
    唯一的完整副本。

    ZUJUAN_NODE_ID 留空时取本机主机名，忘了配也不会撞名。只保留 [a-z0-9_.-]：
    路径分隔符之类的字符一律替换掉，免得节点名把文件写到别的目录去。
    """
    raw = (getattr(config, "ZUJUAN_NODE_ID", "") or "").strip() or socket.gethostname()
    node = _NODE_ID_UNSAFE_RE.sub("-", raw.lower()).strip("-.")
    return node or "node"


class ZuJuanRawJsonlStoreImplement(AbstractStore):
    """
    原始 JSONL 快照：一行一道题，保留整张卡片原文。

    格式严格照 docs/zujuan/题干解析规范.md 第 3.1 节，产出的文件可以直接被原项目的
    离线工具吃掉。文件名 <YYYY-MM-DD>-<节点>-n<序号>.jsonl，写满 ZUJUAN_RAW_SHARD_SIZE
    行开下一个分片；questions.raw_day 记的就是开头的日期。

    ★ 节点只进文件名，不进记录：3.1 节的格式是定死的，多一个键原项目的工具就可能吃不下。
      日期必须留在最前面（raw_day 要和它一致），-n<序号>.jsonl 必须留在最后。
    """

    # meta 的键顺序照抄原程序的输出，方便两边文件直接 diff
    META_FIELDS = (
        ("qtype_code", "qtype_code"),
        ("qtype_name", "qtype"),
        ("difficulty_code", "difficulty_code"),
        ("difficulty_name", "difficulty"),
        ("difficulty_band", "difficulty_band"),
        ("score_rate", "score_rate"),
        ("category_id", "category_id"),
        ("category_name", "category_name"),
        ("source_full", "source"),
        ("source_short", "title_abbr"),
        ("sub_question_count", "sub_question_count"),
        ("year", "year"),
        ("title_abbr", "title_abbr"),
        ("school_year", "school_year"),
        ("grade_level", "grade_level"),
        ("term", "term"),
        ("province", "province"),
        ("province_code", "province_code"),
        ("city", "city"),
        ("source_type", "source_type"),
        ("paper_id", "paper_id"),
        ("used_count", "used_count"),
        ("is_famous_school", "is_famous_school"),
        ("is_real_exam", "is_real_exam"),
        ("updated_hint", "updated_hint"),
        ("detail_url", "detail_url"),
        ("qtype_full", "qtype_full"),
        ("qtype_sub", "qtype_sub"),
    )

    def __init__(self) -> None:
        self._raw_day: Optional[str] = None
        self._path: Optional[str] = None
        self._index = 0
        self._lines = 0
        # 首次写的时候才解析：命令行回写 config 发生在模块导入之后，
        # 在这里读会拿到命令行生效之前的旧值
        self._node: Optional[str] = None

    @classmethod
    def build_record(cls, question: ZujuanQuestion) -> Dict[str, Any]:
        """模型 -> 规范定义的嵌套记录。meta 里只放非空字段，取不到的键整个不出现"""
        meta: Dict[str, Any] = {}
        for key, field in cls.META_FIELDS:
            value = getattr(question, field, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            meta[key] = value

        return {
            "kind": "question",
            "question_id": question.question_id,
            "bank_id": question.bank_id,
            "stem_html": question.stem_html or "",
            "url": question.list_url or "",
            "meta": meta,
            "card_html": question.card_html or "",
            "sources": [s.model_dump() for s in question.sources],
            "tags": list(question.tags),
            "knowledge": [k.model_dump() for k in question.knowledge],
            "formulas": [f.model_dump() for f in question.formulas],
            "images": [i.model_dump() for i in question.images],
            "captured_at": question.captured_at or now_iso(),
        }

    def _resolve_path(self) -> str:
        """
        定位当天该写哪个分片。

        进程启动后第一次写时扫一遍目录接着上次写；之后只在写满时递增，
        不重复扫盘。跨天会自动换到新日期的 n1。只认本节点的分片，
        绝不往别的节点的文件里追加。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        shard_size = int(getattr(config, "ZUJUAN_RAW_SHARD_SIZE", 20000))

        if self._path is not None and self._raw_day == today and self._lines < shard_size:
            return self._path

        raw_dir = getattr(config, "ZUJUAN_RAW_DIR", "data/raw")
        os.makedirs(raw_dir, exist_ok=True)
        if self._node is None:
            self._node = resolve_node_id()

        if self._raw_day != today:
            # 换天了（或首次写），从磁盘上本节点已有的分片接着写
            index = 1
            while True:
                candidate = self._shard_path(raw_dir, today, index)
                if not os.path.exists(candidate):
                    break
                with open(candidate, "r", encoding="utf-8") as f:
                    lines = sum(1 for _ in f)
                if lines < shard_size:
                    self._open_shard(today, candidate, index, lines)
                    return candidate
                index += 1
            self._open_shard(today, candidate, index, 0)
            return candidate

        # 当天写满了，开下一个分片。★ 序号记在状态里而不是从文件名反解 ——
        #   节点名里完全可能带 "-n"（win-node2），rsplit("-n") 会解析错
        path = self._shard_path(raw_dir, today, self._index + 1)
        self._open_shard(today, path, self._index + 1, 0)
        return path

    def _shard_path(self, raw_dir: str, day: str, index: int) -> str:
        return os.path.join(raw_dir, f"{day}-{self._node}-n{index}.jsonl")

    def _open_shard(self, day: str, path: str, index: int, lines: int) -> None:
        self._raw_day, self._path, self._index, self._lines = day, path, index, lines
        utils.logger.info(
            f"[ZuJuanRawJsonl] 原始快照写入 {path}（节点 {self._node}，已有 {lines} 行）"
        )

    @property
    def raw_day(self) -> str:
        """当前分片对应的日期，要写进 questions.raw_day"""
        self._resolve_path()
        return self._raw_day  # type: ignore[return-value]

    async def store_content(self, content_item: ZujuanQuestion):
        path = self._resolve_path()
        record = self.build_record(content_item)
        async with aiofiles.open(path, "a", encoding="utf-8") as f:
            await f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._lines += 1

    async def store_comment(self, comment_item: Dict):
        """组卷网列表页没有评论维度"""

    async def store_creator(self, creator: Dict):
        """本项目不采集任何用户信息"""


class ZuJuanFlatFileStoreImplement(AbstractStore):
    """
    把 questions 那 35 列拍平写成 CSV / JSON 文件。

    只有扁平的标量列，知识点和来源试卷这些多值数据不在这里 ——
    要它们请用 db（关联表）或 jsonl（原始快照）。
    """

    def __init__(self, file_type: str) -> None:
        self.file_type = file_type
        self.writer = AsyncFileWriter(
            platform="zujuan", crawler_type=crawler_type_var.get() or "search"
        )

    async def store_content(self, content_item: ZujuanQuestion):
        row = build_question_row(content_item)
        if self.file_type == "csv":
            await self.writer.write_to_csv(row, "contents")
        else:
            await self.writer.write_single_item_to_json(row, "contents")

    async def store_comment(self, comment_item: Dict):
        """组卷网列表页没有评论维度"""

    async def store_creator(self, creator: Dict):
        """本项目不采集任何用户信息"""


class ZuJuanCsvStoreImplement(ZuJuanFlatFileStoreImplement):
    def __init__(self) -> None:
        super().__init__("csv")


class ZuJuanJsonStoreImplement(ZuJuanFlatFileStoreImplement):
    def __init__(self) -> None:
        super().__init__("json")
