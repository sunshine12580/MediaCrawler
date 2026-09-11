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


# ---------------------------------------------------------------------------
# 多节点：原始快照文件名带节点
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_raw_jsonl_file_name_carries_node_id(tmp_path, monkeypatch):
    """★ 两台机器同时跑，各自都从 n1 开始写。文件名不带节点的话，
    合到一个目录就会互相覆盖 —— 而这是卡片原文唯一的完整副本"""
    monkeypatch.setattr(config, "ZUJUAN_RAW_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "win10")
    store = ZuJuanRawJsonlStoreImplement()
    await store.store_content(make_question(question_id="1"))
    (name,) = [p.name for p in tmp_path.iterdir()]
    assert name == f"{store.raw_day}-win10-n1.jsonl"
    # 日期必须留在最前面：questions.raw_day 靠它回查快照
    assert name.startswith(store.raw_day)


@pytest.mark.asyncio
async def test_two_nodes_in_one_dir_never_share_a_file(tmp_path, monkeypatch):
    """同一个目录里两个节点各写各的，谁也不往对方的分片里追加"""
    monkeypatch.setattr(config, "ZUJUAN_RAW_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "win11")
    a = ZuJuanRawJsonlStoreImplement()
    await a.store_content(make_question(question_id="a"))

    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "win10")
    b = ZuJuanRawJsonlStoreImplement()
    await b.store_content(make_question(question_id="b"))

    assert a._path != b._path
    assert len(open(a._path, encoding="utf-8").read().splitlines()) == 1
    assert len(open(b._path, encoding="utf-8").read().splitlines()) == 1


@pytest.mark.asyncio
async def test_node_is_fixed_for_the_life_of_the_process(tmp_path, monkeypatch):
    """首次写时定下节点，之后 config 再怎么变也不换文件 —— 半路换名会把
    同一个进程的产出拆到两个节点名下"""
    monkeypatch.setattr(config, "ZUJUAN_RAW_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "win11")
    store = ZuJuanRawJsonlStoreImplement()
    await store.store_content(make_question(question_id="1"))
    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "something-else")
    await store.store_content(make_question(question_id="2"))
    (name,) = [p.name for p in tmp_path.iterdir()]
    assert "-win11-" in name


@pytest.mark.asyncio
async def test_rollover_with_node_id_containing_dash_n(tmp_path, monkeypatch):
    """★ 节点名里带 -n（win-node2）时分片序号不能被解析错。
    旧代码用 rsplit("-n") 从文件名反解序号，碰上这种名字会炸或者跳号"""
    monkeypatch.setattr(config, "ZUJUAN_RAW_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ZUJUAN_RAW_SHARD_SIZE", 1)
    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "win-node2")
    store = ZuJuanRawJsonlStoreImplement()
    for i in range(3):
        await store.store_content(make_question(question_id=str(i)))
    names = sorted(p.name for p in tmp_path.iterdir())
    day = names[0][:10]
    assert names == [f"{day}-win-node2-n{i}.jsonl" for i in (1, 2, 3)]


@pytest.mark.asyncio
async def test_resume_only_appends_to_own_node_shard(tmp_path, monkeypatch):
    """重启后接着写，只认本节点的分片；目录里别的节点的文件一行都不碰"""
    monkeypatch.setattr(config, "ZUJUAN_RAW_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ZUJUAN_RAW_SHARD_SIZE", 10)
    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "win10")
    other = ZuJuanRawJsonlStoreImplement()
    await other.store_content(make_question(question_id="x"))

    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "win11")
    first = ZuJuanRawJsonlStoreImplement()
    await first.store_content(make_question(question_id="1"))
    again = ZuJuanRawJsonlStoreImplement()
    await again.store_content(make_question(question_id="2"))

    assert again._path == first._path
    assert len(open(first._path, encoding="utf-8").read().splitlines()) == 2
    assert len(open(other._path, encoding="utf-8").read().splitlines()) == 1


def test_node_id_defaults_to_hostname(monkeypatch):
    """留空取主机名：忘了配也不会两台撞名"""
    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "")
    monkeypatch.setattr(_store_impl.socket, "gethostname", lambda: "DESKTOP-7H3K2LQ")
    assert _store_impl.resolve_node_id() == "desktop-7h3k2lq"


def test_node_id_is_sanitized(monkeypatch):
    """节点名里的路径分隔符不能把文件写到别的目录去"""
    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "../Win 11\\x")
    node = _store_impl.resolve_node_id()
    assert node == "win-11-x"
    assert "/" not in node and "\\" not in node and not node.startswith(".")


def test_node_id_never_empty(monkeypatch):
    monkeypatch.setattr(config, "ZUJUAN_NODE_ID", "...")
    assert _store_impl.resolve_node_id() == "node"
