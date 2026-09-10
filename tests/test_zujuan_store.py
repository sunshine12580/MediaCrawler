# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_zujuan_store.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网入库单测，守住 docs/zujuan/题干入库规范.md 里那几条会造成数据损失的规则：
只写非空列、不碰其它阶段的产物列、已有题干就整题跳过、关联表先删后插。
"""
import json
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.sql import Delete, Insert, Select, Update

import config
from database.models import ZujuanQuestion as ZujuanQuestionOrm
from model.m_zujuan import ZujuanKnowledge, ZujuanQuestion, ZujuanSource
from store.zujuan import _store_impl
from store.zujuan._store_impl import (
    QUESTION_COLUMNS,
    ZuJuanDbStoreImplement,
    ZuJuanRawJsonlStoreImplement,
    build_question_row,
    dedup_knowledge,
    dedup_sources,
)

# 其它阶段（答案抓取 / 离线渲染）的产物列，抓取任务一列都不许碰
FORBIDDEN_COLUMNS = (
    "stem_md", "stem_at", "render_status", "stem_html_local",
    "stem_body_html", "stem_body_html_local", "stem_body_md", "stem_body_text",
    "options_html", "options_html_local", "options_md", "options_text",
    "blank_count", "sub_question_cnt", "option_count", "orig_no",
    "answer_img", "answer_md", "answer_status", "answer_at",
)


def make_question(**overrides) -> ZujuanQuestion:
    data = dict(
        question_id="35238538",
        bank_id="2",
        grade="middle",
        stem_html="<p>题干</p>",
        stem_status="html_saved",
        stem_hash="a" * 32,
        qtype="解答题",
        score_rate=0.4,
        is_famous_school=0,
        is_real_exam=0,
        used_count=323,
        list_url="https://zujuan.xkw.com/czsx/zsd5249/o2",
        raw_day="2026-09-03",
    )
    data.update(overrides)
    return ZujuanQuestion(**data)


# --------------------------------------------------------------------------
# 结构性保证：ORM 里根本没有那些列，写代码时想碰也碰不到
# --------------------------------------------------------------------------


def test_orm_declares_no_other_stage_columns():
    columns = set(ZujuanQuestionOrm.__table__.columns.keys())
    assert columns.isdisjoint(FORBIDDEN_COLUMNS)


def test_orm_does_not_declare_stem_text():
    # stem_text 的口径是离线产物（裸 LaTeX + [图N] 占位），抓取阶段产不出来
    assert "stem_text" not in ZujuanQuestionOrm.__table__.columns


def test_orm_maps_the_real_tables():
    assert ZujuanQuestionOrm.__tablename__ == "questions"
    assert set(ZujuanQuestionOrm.__table__.columns.keys()) == set(QUESTION_COLUMNS) | {
        "first_seen_at"
    }


# --------------------------------------------------------------------------
# 只写非空列
# --------------------------------------------------------------------------


def test_build_question_row_drops_none_and_blank():
    row = build_question_row(make_question(city=None, term="", province="   "))
    assert "city" not in row
    assert "term" not in row
    assert "province" not in row


def test_build_question_row_keeps_zero():
    # 0 是"确认没有名校角标"，不是"没解析到" —— 丢了它就等于把已有值冲成空
    row = build_question_row(make_question(is_famous_school=0, is_real_exam=0, used_count=0))
    assert row["is_famous_school"] == 0
    assert row["is_real_exam"] == 0
    assert row["used_count"] == 0


def test_build_question_row_never_leaks_other_columns():
    row = build_question_row(make_question())
    assert set(row).issubset(set(QUESTION_COLUMNS))
    assert set(row).isdisjoint(FORBIDDEN_COLUMNS)


# --------------------------------------------------------------------------
# 关联表去重
# --------------------------------------------------------------------------


def test_dedup_knowledge_keeps_first_and_renumbers_ord():
    q = make_question(knowledge=[
        ZujuanKnowledge(id="zsd5249", name="反比例函数与几何综合"),
        ZujuanKnowledge(id="zsd5602", name="证明四边形是菱形"),
        ZujuanKnowledge(id="zsd5249", name="问题解决能力"),  # 能力标签，id 撞车
    ])
    rows = dedup_knowledge(q)
    # 主键是 (question_id, knowledge_id)，不去重会主键冲突
    assert [r["knowledge_id"] for r in rows] == ["zsd5249", "zsd5602"]
    assert [r["knowledge_name"] for r in rows] == ["反比例函数与几何综合", "证明四边形是菱形"]
    assert [r["ord"] for r in rows] == [0, 1]


def test_dedup_sources_by_paper_id():
    q = make_question(sources=[
        ZujuanSource(paper_id="3410462", bank_id="2", title="卷A"),
        ZujuanSource(paper_id="3367834", bank_id="2", title="卷B"),
        ZujuanSource(paper_id="3410462", bank_id="2", title="卷A"),
    ])
    rows = dedup_sources(q)
    assert [r["paper_id"] for r in rows] == ["3410462", "3367834"]
    assert [r["ord"] for r in rows] == [0, 1]


def test_dedup_skips_entries_without_id():
    q = make_question(
        knowledge=[ZujuanKnowledge(id="", name="没有ID")],
        sources=[ZujuanSource(paper_id="", title="没有ID")],
    )
    assert dedup_knowledge(q) == []
    assert dedup_sources(q) == []


# --------------------------------------------------------------------------
# 写入分支：跳过 / 插入 / 补半成品
# --------------------------------------------------------------------------


class FakeRow:
    def __init__(self, stem_hash):
        self.stem_hash = stem_hash


class FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeSession:
    """记录下所有执行过的语句，供断言检查"""

    def __init__(self, existing=None):
        self.existing = existing
        self.statements = []

    async def execute(self, statement, params=None):
        self.statements.append((statement, params))
        if isinstance(statement, Select):
            return FakeResult(self.existing)
        return None

    async def commit(self):
        pass

    async def rollback(self):
        pass

    def kinds(self):
        return [type(s).__name__ for s, _ in self.statements]

    def values_of(self, stmt_type):
        """取语句里 SET / VALUES 的列名（不含 WHERE 的绑定参数）"""
        for statement, _ in self.statements:
            if isinstance(statement, stmt_type) and getattr(statement, "_values", None):
                return {column.name for column in statement._values}
        return None


@pytest.fixture
def patched_session(monkeypatch):
    holder = {}

    def install(existing=None):
        session = FakeSession(existing)
        holder["session"] = session

        @asynccontextmanager
        async def fake_get_session():
            yield session

        monkeypatch.setattr(_store_impl, "get_session", fake_get_session)
        return session

    return install


@pytest.mark.asyncio
async def test_skip_when_stem_hash_present(patched_session):
    session = patched_session(existing=FakeRow(stem_hash="b" * 32))
    await ZuJuanDbStoreImplement().store_content(make_question())
    # 只查了一次，什么都没写 —— 关联表也不动
    assert session.kinds() == ["Select"]


@pytest.mark.asyncio
async def test_insert_when_brand_new(patched_session):
    session = patched_session(existing=None)
    await ZuJuanDbStoreImplement().store_content(make_question())
    kinds = session.kinds()
    assert kinds[0] == "Select"
    assert "Insert" in kinds
    assert kinds.count("Delete") == 2  # 两张关联表先删后插
    assert "Update" not in kinds
    # 新题才写 first_seen_at
    assert "first_seen_at" in session.values_of(Insert)


@pytest.mark.asyncio
async def test_update_half_baked_row_without_touching_first_seen_at(patched_session):
    session = patched_session(existing=FakeRow(stem_hash=None))
    await ZuJuanDbStoreImplement().store_content(make_question())
    kinds = session.kinds()
    assert "Update" in kinds
    assert "Insert" not in kinds[:2]
    columns = session.values_of(Update)
    # ★first_seen_at 只在第一次插入时写，更新时改了就丢了"最早什么时候见到"
    assert "first_seen_at" not in columns


@pytest.mark.asyncio
async def test_update_only_sets_parsed_non_empty_columns(patched_session):
    session = patched_session(existing=FakeRow(stem_hash=""))
    await ZuJuanDbStoreImplement().store_content(make_question(city=None, term=None))
    columns = session.values_of(Update)
    # ★ SET 的列必须严格等于这次解析出来的非空列，一个不多。
    #   多一列（哪怕设成 NULL）就会把其它阶段写好的数据冲掉
    assert columns == set(build_question_row(make_question(city=None, term=None)))
    assert "city" not in columns
    assert columns.isdisjoint(FORBIDDEN_COLUMNS)


@pytest.mark.asyncio
async def test_skip_can_be_disabled(patched_session, monkeypatch):
    monkeypatch.setattr(config, "ZUJUAN_SKIP_EXISTING", False)
    session = patched_session(existing=FakeRow(stem_hash="b" * 32))
    await ZuJuanDbStoreImplement().store_content(make_question())
    assert "Update" in session.kinds()


@pytest.mark.asyncio
async def test_question_without_id_is_not_written(patched_session):
    session = patched_session(existing=None)
    await ZuJuanDbStoreImplement().store_content(make_question(question_id=None))
    assert session.statements == []


# --------------------------------------------------------------------------
# 原始 JSONL 快照
# --------------------------------------------------------------------------


def test_raw_record_shape():
    q = make_question(
        qtype_code="1103", qtype_full="解答题-计算题", qtype_sub="计算题",
        knowledge=[ZujuanKnowledge(id="zsd5249", name="知识点")],
        sources=[ZujuanSource(paper_id="3410462", bank_id="2", title="卷A", url="/2p3410462.html")],
        tags=["名校"], card_html="<div>整卡片</div>", captured_at="2026-09-03T10:00:00",
    )
    record = ZuJuanRawJsonlStoreImplement.build_record(q)
    assert record["kind"] == "question"
    assert record["question_id"] == "35238538"
    assert record["card_html"] == "<div>整卡片</div>"
    assert record["url"] == "https://zujuan.xkw.com/czsx/zsd5249/o2"
    assert record["tags"] == ["名校"]
    assert record["knowledge"] == [{"id": "zsd5249", "name": "知识点"}]
    assert record["sources"][0]["paper_id"] == "3410462"
    assert record["captured_at"] == "2026-09-03T10:00:00"
    assert record["meta"]["qtype_name"] == "解答题"
    assert record["meta"]["qtype_full"] == "解答题-计算题"
    assert record["meta"]["qtype_sub"] == "计算题"


def test_raw_record_meta_omits_empty_keeps_zero():
    record = ZuJuanRawJsonlStoreImplement.build_record(
        make_question(city=None, term="", is_famous_school=0)
    )
    # meta 里只放非空字段，取不到的键整个不出现，不写 null 占位
    assert "city" not in record["meta"]
    assert "term" not in record["meta"]
    # 但 0 是有意义的取值
    assert record["meta"]["is_famous_school"] == 0


@pytest.mark.asyncio
async def test_raw_jsonl_shard_rollover(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ZUJUAN_RAW_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ZUJUAN_RAW_SHARD_SIZE", 2)
    store = ZuJuanRawJsonlStoreImplement()

    for i in range(3):
        await store.store_content(make_question(question_id=str(i)))

    files = sorted(p.name for p in tmp_path.iterdir())
    assert len(files) == 2
    assert files[0].endswith("-n1.jsonl") and files[1].endswith("-n2.jsonl")
    first = (tmp_path / files[0]).read_text(encoding="utf-8").strip().splitlines()
    assert len(first) == 2
    assert json.loads(first[0])["question_id"] == "0"
    # raw_day 必须和文件名里的日期一致，questions.raw_day 靠它回查快照
    assert files[0].startswith(store.raw_day)


@pytest.mark.asyncio
async def test_raw_jsonl_appends_to_existing_shard(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ZUJUAN_RAW_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ZUJUAN_RAW_SHARD_SIZE", 10)
    store = ZuJuanRawJsonlStoreImplement()
    await store.store_content(make_question(question_id="1"))
    path = store._path

    # 新进程接着写同一个分片，而不是覆盖
    another = ZuJuanRawJsonlStoreImplement()
    await another.store_content(make_question(question_id="2"))
    assert another._path == path
    assert len(open(path, encoding="utf-8").read().strip().splitlines()) == 2
