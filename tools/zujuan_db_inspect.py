# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/zujuan_db_inspect.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网题库表结构只读巡检

对照《题干入库规范.md》检查 questions / question_knowledge / question_sources
三张表的真实结构，报告缺列、多列、类型不符、字符集问题。

**严格只读**：只执行 SHOW CREATE TABLE、information_schema 查询、SELECT COUNT(*)
和可选的样本行读取，不做任何写操作、不建表、不改表。

用法：
    uv run python tools/zujuan_db_inspect.py
    uv run python tools/zujuan_db_inspect.py --out docs/zujuan/db_snapshot.txt
    uv run python tools/zujuan_db_inspect.py --sample 0        # 不读样本行
    uv run python tools/zujuan_db_inspect.py --no-charset-param # 不加 ?charset=utf8mb4

连接信息从项目根目录的 .env 读取（MYSQL_DB_HOST / PORT / USER / PWD / NAME）。
"""

import argparse
import asyncio
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# Windows 控制台默认 GBK，中文输出会炸，这里强制 utf-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# 期望结构：抄自《题干入库规范.md》第 3 节 DDL
# ---------------------------------------------------------------------------

# questions 表里这次任务负责写的列
QUESTIONS_OWNED: List[Tuple[str, str]] = [
    ("question_id", "varchar(64)"),
    ("grade", "varchar(8)"),
    ("bank_id", "varchar(16)"),
    ("stem_html", "mediumtext"),
    ("stem_text", "mediumtext"),
    ("stem_status", "varchar(16)"),
    ("stem_hash", "varchar(32)"),
    ("qtype", "varchar(32)"),
    ("qtype_code", "varchar(16)"),
    ("qtype_full", "varchar(32)"),
    ("qtype_sub", "varchar(16)"),
    ("difficulty", "varchar(16)"),
    ("difficulty_code", "varchar(8)"),
    ("difficulty_band", "varchar(8)"),
    ("score_rate", "double"),
    ("source", "text"),
    ("title_abbr", "varchar(128)"),
    ("category_id", "varchar(16)"),
    ("category_name", "varchar(64)"),
    ("school_year", "varchar(16)"),
    ("year", "int"),
    ("grade_level", "varchar(16)"),
    ("term", "varchar(16)"),
    ("province", "varchar(16)"),
    ("province_code", "varchar(8)"),
    ("city", "varchar(32)"),
    ("source_type", "varchar(32)"),
    ("paper_id", "varchar(32)"),
    ("used_count", "int"),
    ("is_famous_school", "tinyint"),
    ("is_real_exam", "tinyint"),
    ("list_url", "text"),
    ("knowledge_id", "varchar(32)"),
    ("knowledge_tags", "text"),
    ("raw_day", "varchar(10)"),
    ("first_seen_at", "varchar(32)"),
]

# 其它阶段专属的列 —— 抓取任务禁止写入，这里只用来确认它们真的存在
QUESTIONS_FORBIDDEN: List[str] = [
    "stem_md", "stem_at", "render_status", "stem_html_local",
    "stem_body_html", "stem_body_html_local", "stem_body_md", "stem_body_text",
    "options_html", "options_html_local", "options_md", "options_text",
    "blank_count", "sub_question_cnt", "option_count", "orig_no",
    "answer_img", "answer_md", "answer_status", "answer_at",
]

KNOWLEDGE_OWNED: List[Tuple[str, str]] = [
    ("question_id", "varchar(64)"),
    ("knowledge_id", "varchar(32)"),
    ("knowledge_name", "varchar(128)"),
    ("ord", "int"),
]

SOURCES_OWNED: List[Tuple[str, str]] = [
    ("question_id", "varchar(64)"),
    ("paper_id", "varchar(32)"),
    ("paper_title", "text"),
    ("ord", "int"),
]

TABLES = {
    "questions": (QUESTIONS_OWNED, QUESTIONS_FORBIDDEN),
    "question_knowledge": (KNOWLEDGE_OWNED, []),
    "question_sources": (SOURCES_OWNED, []),
}

# 只有这些短字段适合直接打印样本值，大文本只报长度
SAMPLE_SKIP_TYPES = ("mediumtext", "longtext", "text")


class Report:
    """收集输出，最后一次性打印 / 落盘"""

    def __init__(self) -> None:
        self.lines: List[str] = []
        self.problems: List[str] = []

    def __call__(self, line: str = "") -> None:
        self.lines.append(line)

    def problem(self, line: str) -> None:
        self.problems.append(line)
        self.lines.append(f"  [!] {line}")

    def dump(self, out_path: Optional[str]) -> None:
        body = "\n".join(self.lines)
        print(body)
        if out_path:
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(body + "\n")
            print(f"\n已写入: {out_path}")


def normalize_type(col_type: str) -> str:
    """int(11) -> int, tinyint(4) -> tinyint，便于和期望类型比较"""
    t = col_type.lower().strip()
    for base in ("int", "tinyint", "smallint", "bigint"):
        if t.startswith(base + "(") or t == base:
            return base
    return t.replace(" unsigned", "").strip()


def build_db_url(cfg: Dict[str, Any], with_charset: bool) -> str:
    from urllib.parse import quote_plus

    url = (
        f"mysql+asyncmy://{quote_plus(str(cfg['user']))}:{quote_plus(str(cfg['password']))}"
        f"@{cfg['host']}:{cfg['port']}/{cfg['db_name']}"
    )
    if with_charset:
        url += "?charset=utf8mb4"
    return url


async def fetch_all(conn, sql: str, **params) -> List[Dict[str, Any]]:
    res = await conn.execute(text(sql), params)
    return [dict(row) for row in res.mappings()]


async def inspect_server(conn, rep: Report, db_name: str) -> None:
    rep("=" * 78)
    rep("服务器与连接")
    rep("=" * 78)

    ver = await fetch_all(conn, "SELECT VERSION() AS v")
    rep(f"  MySQL 版本            : {ver[0]['v']}")

    vars_sql = """
        SELECT @@character_set_server AS cs_server,
               @@collation_server     AS coll_server,
               @@character_set_client AS cs_client,
               @@character_set_connection AS cs_conn,
               @@character_set_results AS cs_results
    """
    v = (await fetch_all(conn, vars_sql))[0]
    rep(f"  服务端字符集/排序规则 : {v['cs_server']} / {v['coll_server']}")
    rep(f"  连接字符集 client/conn/results: {v['cs_client']} / {v['cs_conn']} / {v['cs_results']}")
    for key, label in (("cs_client", "client"), ("cs_conn", "connection"), ("cs_results", "results")):
        if v[key] != "utf8mb4":
            rep.problem(f"连接字符集 {label} = {v[key]}，不是 utf8mb4，4 字节字符会被截断或报错")

    schema = await fetch_all(
        conn,
        "SELECT DEFAULT_CHARACTER_SET_NAME AS cs, DEFAULT_COLLATION_NAME AS coll "
        "FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :db",
        db=db_name,
    )
    if schema:
        rep(f"  库 `{db_name}` 默认      : {schema[0]['cs']} / {schema[0]['coll']}")
        if schema[0]["cs"] != "utf8mb4":
            rep.problem(f"库默认字符集是 {schema[0]['cs']}，规范要求 utf8mb4")
    else:
        rep.problem(f"库 `{db_name}` 在 information_schema 里查不到")

    plugin = await fetch_all(conn, "SELECT CURRENT_USER() AS u")
    rep(f"  当前连接用户          : {plugin[0]['u']}")

    grants = await fetch_all(conn, "SHOW GRANTS")
    rep("  权限:")
    for g in grants:
        rep(f"      {list(g.values())[0]}")
    rep()


async def inspect_table(
    conn, rep: Report, db_name: str, table: str,
    owned: List[Tuple[str, str]], forbidden: List[str], sample_n: int,
) -> None:
    rep("=" * 78)
    rep(f"表 `{table}`")
    rep("=" * 78)

    meta = await fetch_all(
        conn,
        "SELECT ENGINE, TABLE_COLLATION, TABLE_ROWS, CREATE_TIME "
        "FROM information_schema.TABLES WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :t",
        db=db_name, t=table,
    )
    if not meta:
        rep.problem(f"表 `{table}` 不存在")
        rep()
        return

    m = meta[0]
    rep(f"  引擎 / 排序规则       : {m['ENGINE']} / {m['TABLE_COLLATION']}")
    rep(f"  创建时间              : {m['CREATE_TIME']}")
    if m["TABLE_COLLATION"] and not str(m["TABLE_COLLATION"]).startswith("utf8mb4"):
        rep.problem(f"表排序规则 {m['TABLE_COLLATION']} 不是 utf8mb4_*")

    cnt = await fetch_all(conn, f"SELECT COUNT(*) AS c FROM `{table}`")
    rep(f"  实际行数 COUNT(*)     : {cnt[0]['c']:,}")

    cols = await fetch_all(
        conn,
        "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, "
        "       CHARACTER_SET_NAME, COLLATION_NAME, ORDINAL_POSITION "
        "FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :t ORDER BY ORDINAL_POSITION",
        db=db_name, t=table,
    )
    actual = {c["COLUMN_NAME"]: c for c in cols}
    rep(f"  列数                  : {len(cols)}")
    rep()

    # ---- 逐列比对 ----
    rep("  -- 本次任务负责的列 --")
    rep(f"  {'列名':<20} {'期望类型':<14} {'实际类型':<16} {'NULL':<6} {'默认值':<12} 判定")
    rep(f"  {'-'*20} {'-'*14} {'-'*16} {'-'*6} {'-'*12} {'-'*8}")
    missing: List[str] = []
    type_bad: List[str] = []
    for name, want in owned:
        c = actual.get(name)
        if c is None:
            missing.append(name)
            rep(f"  {name:<20} {want:<14} {'<缺失>':<16} {'-':<6} {'-':<12} 缺列")
            continue
        got = normalize_type(c["COLUMN_TYPE"])
        ok = got == normalize_type(want)
        if not ok:
            type_bad.append(f"{name}: 期望 {want}, 实际 {c['COLUMN_TYPE']}")
        default = "NULL" if c["COLUMN_DEFAULT"] is None else str(c["COLUMN_DEFAULT"])
        rep(
            f"  {name:<20} {want:<14} {c['COLUMN_TYPE']:<16} "
            f"{c['IS_NULLABLE']:<6} {default[:12]:<12} {'OK' if ok else '类型不符'}"
        )
    rep()
    for name in missing:
        rep.problem(f"`{table}`.`{name}` 缺列 —— 写入时会报 Unknown column")
    for msg in type_bad:
        rep.problem(f"`{table}`.{msg} —— 类型不符可能静默转换")

    # ---- 禁写列 ----
    if forbidden:
        present = [n for n in forbidden if n in actual]
        absent = [n for n in forbidden if n not in actual]
        rep(f"  -- 其它阶段专属列（禁止写入）：表中存在 {len(present)}/{len(forbidden)} 个 --")
        rep(f"     存在: {', '.join(present) if present else '（无）'}")
        if absent:
            rep(f"     表中没有: {', '.join(absent)}")
        rep()

    # ---- 规范没提到、表里却有的列 ----
    known = {n for n, _ in owned} | set(forbidden)
    extra = [c["COLUMN_NAME"] for c in cols if c["COLUMN_NAME"] not in known]
    if extra:
        rep(f"  -- 规范未提及、但表里存在的列（{len(extra)} 个）--")
        for name in extra:
            c = actual[name]
            rep(f"     {name:<24} {c['COLUMN_TYPE']:<18} NULL={c['IS_NULLABLE']}")
        rep()

    # ---- 非 utf8mb4 的字符列 ----
    bad_cs = [
        c for c in cols
        if c["CHARACTER_SET_NAME"] and c["CHARACTER_SET_NAME"] != "utf8mb4"
    ]
    if bad_cs:
        for c in bad_cs:
            rep.problem(
                f"`{table}`.`{c['COLUMN_NAME']}` 字符集是 {c['CHARACTER_SET_NAME']}，不是 utf8mb4"
            )
        rep()

    # ---- 索引 ----
    idx = await fetch_all(
        conn,
        "SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME "
        "FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :t "
        "ORDER BY INDEX_NAME, SEQ_IN_INDEX",
        db=db_name, t=table,
    )
    grouped: Dict[str, List[str]] = {}
    unique: Dict[str, bool] = {}
    for r in idx:
        grouped.setdefault(r["INDEX_NAME"], []).append(r["COLUMN_NAME"])
        unique[r["INDEX_NAME"]] = r["NON_UNIQUE"] == 0
    rep("  -- 索引 --")
    for name, cols_in in grouped.items():
        kind = "PRIMARY" if name == "PRIMARY" else ("UNIQUE" if unique[name] else "KEY")
        rep(f"     {kind:<8} {name:<20} ({', '.join(cols_in)})")
    if "PRIMARY" not in grouped:
        rep.problem(f"`{table}` 没有主键")
    rep()

    # ---- 建表语句原文 ----
    ddl = await fetch_all(conn, f"SHOW CREATE TABLE `{table}`")
    rep("  -- SHOW CREATE TABLE --")
    for line in str(list(ddl[0].values())[1]).splitlines():
        rep(f"     {line}")
    rep()

    # ---- 样本行 ----
    if sample_n > 0 and cnt[0]["c"] > 0:
        short_cols = [
            c["COLUMN_NAME"] for c in cols
            if normalize_type(c["COLUMN_TYPE"]) not in SAMPLE_SKIP_TYPES
        ]
        pick = short_cols[:18]
        col_sql = ", ".join(f"`{c}`" for c in pick)
        rows = await fetch_all(conn, f"SELECT {col_sql} FROM `{table}` LIMIT {int(sample_n)}")
        rep(f"  -- 样本行（{len(rows)} 行，只取非大文本列的前 {len(pick)} 列）--")
        for i, row in enumerate(rows):
            rep(f"     [{i}]")
            for k, val in row.items():
                shown = "NULL" if val is None else repr(val)[:80]
                rep(f"        {k:<20} = {shown}   <{type(val).__name__}>")
        rep()


async def inspect_data_health(conn, rep: Report) -> None:
    """几个直接影响写入策略的统计"""
    rep("=" * 78)
    rep("数据现状（影响写入策略）")
    rep("=" * 78)

    q = """
        SELECT
            COUNT(*)                                                   AS total,
            SUM(stem_hash IS NULL OR stem_hash = '')                   AS no_stem_hash,
            SUM(stem_html IS NULL OR stem_html = '')                   AS no_stem_html,
            SUM(grade IS NOT NULL AND grade <> '')                     AS has_grade,
            COUNT(DISTINCT bank_id)                                    AS bank_kinds
        FROM questions
    """
    try:
        r = (await fetch_all(conn, q))[0]
        rep(f"  questions 总行数              : {r['total']:,}")
        rep(f"  stem_hash 为空（半成品，会补写）: {r['no_stem_hash']:,}")
        rep(f"  stem_html 为空                : {r['no_stem_html']:,}")
        rep(f"  → 按规范 5.1，本次运行会跳过 {int(r['total']) - int(r['no_stem_hash'] or 0):,} 道已有题")
        rep(f"  bank_id 取值种类              : {r['bank_kinds']}")
    except Exception as e:
        rep.problem(f"questions 统计失败: {e}")

    for col, label in (("answer_status", "答案阶段"), ("render_status", "离线渲染阶段")):
        try:
            rows = await fetch_all(
                conn,
                f"SELECT `{col}` AS v, COUNT(*) AS c FROM questions "
                f"GROUP BY `{col}` ORDER BY c DESC LIMIT 8",
            )
            dist = ", ".join(f"{r['v']}={r['c']:,}" for r in rows)
            rep(f"  {label} {col:<16}: {dist}")
        except Exception as e:
            rep(f"  {label} {col:<16}: 查询失败 ({e})")

    for t in ("question_knowledge", "question_sources"):
        try:
            r = (await fetch_all(conn, f"SELECT COUNT(*) AS c FROM `{t}`"))[0]
            rep(f"  {t:<20} 行数     : {r['c']:,}")
        except Exception as e:
            rep(f"  {t:<20} 行数     : 查询失败 ({e})")

    try:
        r = await fetch_all(conn, "SELECT `grade`, COUNT(*) AS c FROM questions GROUP BY `grade`")
        dist = ", ".join("{}={:,}".format(x["grade"], x["c"]) for x in r)
        rep(f"  grade 分布                    : {dist}")
    except Exception as e:
        rep(f"  grade 分布                    : 查询失败 ({e})")
    rep()


async def main() -> int:
    parser = argparse.ArgumentParser(description="组卷网题库表结构只读巡检（不做任何写操作）")
    parser.add_argument("--out", default=None, help="把报告同时写到这个文件")
    parser.add_argument("--sample", type=int, default=2, help="每张表读几行样本，0 表示不读")
    parser.add_argument(
        "--no-charset-param", action="store_true",
        help="连接串不加 ?charset=utf8mb4（复现项目当前的连接方式）",
    )
    args = parser.parse_args()

    env_path = os.path.join(PROJECT_ROOT, ".env")
    if load_dotenv and os.path.exists(env_path):
        load_dotenv(env_path)
        loaded = f"已加载 {env_path}"
    elif not os.path.exists(env_path):
        loaded = f"未找到 {env_path}，改用当前环境变量"
    else:
        loaded = "python-dotenv 不可用，改用当前环境变量"

    cfg = {
        "host": os.getenv("MYSQL_DB_HOST", "localhost"),
        "port": os.getenv("MYSQL_DB_PORT", "3306"),
        "user": os.getenv("MYSQL_DB_USER", "root"),
        "password": os.getenv("MYSQL_DB_PWD", ""),
        "db_name": os.getenv("MYSQL_DB_NAME", ""),
    }

    rep = Report()
    rep("组卷网题库表结构巡检报告（只读）")
    rep(f"  配置来源: {loaded}")
    rep(f"  目标    : {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['db_name']}")
    rep(f"  连接串  : {'带' if not args.no_charset_param else '不带'} ?charset=utf8mb4")
    rep()

    placeholders = [k for k, v in cfg.items() if isinstance(v, str) and v.startswith("改成")]
    if not cfg["db_name"] or placeholders:
        if placeholders:
            rep.problem(f".env 里这几项还是占位符，请先填成真实值: {', '.join(placeholders)}")
        else:
            rep.problem("MYSQL_DB_NAME 为空，请先在项目根目录的 .env 里填好连接信息")
        rep.dump(args.out)
        return 2

    engine = create_async_engine(
        build_db_url(cfg, with_charset=not args.no_charset_param), echo=False
    )
    try:
        async with engine.connect() as conn:
            await inspect_server(conn, rep, cfg["db_name"])
            for table, (owned, forbidden) in TABLES.items():
                await inspect_table(conn, rep, cfg["db_name"], table, owned, forbidden, args.sample)
            await inspect_data_health(conn, rep)
    except Exception as e:
        rep.problem(f"连接或查询失败: {type(e).__name__}: {e}")
        rep()
        rep("排查提示:")
        rep("  - MySQL 8.4 默认只支持 caching_sha2_password，asyncmy 0.2.10 支持它；")
        rep("    如果报认证相关错误，先用命令行客户端连一次让服务端缓存住，或给连接开 SSL")
        rep("  - 确认 .env 里 MYSQL_DB_* 五项都填对了，库名是已经建好 questions 表的那个库")
        rep.dump(args.out)
        await engine.dispose()
        return 1
    finally:
        await engine.dispose()

    rep("=" * 78)
    rep(f"结论：发现 {len(rep.problems)} 个问题")
    rep("=" * 78)
    if rep.problems:
        for i, p in enumerate(rep.problems, 1):
            rep(f"  {i}. {p}")
    else:
        rep("  表结构与《题干入库规范.md》一致，可以按规范直接写入。")
    rep.dump(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
