# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zujuan/slicing.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网按知识点抓取的翻页与切片策略（见 docs/zujuan/知识点切片抓取规范.md）。

这个模块只放**纯计算**：维度定义、slice_key 与 URL 的互译、级联下钻规则、
页码区间运算。不碰网络也不碰数据库，便于单测覆盖。

四个容易踩的点：

1. 翻页硬顶是**针对每一个具体 URL 单独计算**的：999 页 = 9990 道。加一个筛选
   条件就是一个新 URL，有它自己独立的额度 —— 切片能绕开硬顶，全部原理就这一句。
2. slice_key 用的短码（``t1``/``d1``/``s1``/``y2020``）和拼 URL 用的站点码
   （``qt1101``/``d1``/``01``/``y2020``）是**两套命名空间**，必须翻译。解答题
   子题型更特殊 —— 它不是独立的一段，而是接在题型码后面的两位：
   ``qt1103`` + ``05`` = ``qt110305``。
3. slice_key 的拼接顺序固定按维度顺序（题型→难度→子题型→年份），不按填写顺序。
   顺序一变，同一组筛选条件就会得到不同的 key，断点续采查不到上次那一行，
   会从头把整个知识点再切一遍。
4. 难度维度在库里对应的是 ``questions.difficulty_band``（由得分率重算的 3 档），
   **不是** ``difficulty_code``（按钮上的 5 档）—— 两套编码的数值会撞车。
   已用线上数据核对：zsd4718 的 t4d1/t4d2/t4d3 三片按 difficulty_band 统计
   得 6274/4427/118，与 knowledge_slice 里记的 collected 完全一致。
"""

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from .help import ZUJUAN_HOST

# ---------------------------------------------------------------------------
# 翻页硬顶
# ---------------------------------------------------------------------------

# 一页固定 10 道
PAGE_SIZE = 10

# 实测：翻到第 999 页就到头了。第 1000 页开始服务端不报错、也不返回空页，
# 而是把第 999 页原样重复返回 —— 不检测的话循环会一直跑，反复处理同样 10 道题，
# 表现是"程序在跑但入库数不涨"，这是最难发现的一类故障
MAX_PAGE = 999

# 任何一个筛选条件组合出来的 URL，最多只能通过翻页拿到这么多道题
HARD_CAP = PAGE_SIZE * MAX_PAGE  # 9990

# 年份维度里 "更早以前"（y-1）的含义：比这一年还早
EARLIEST_YEAR = 2020


# ---------------------------------------------------------------------------
# 切片维度
# ---------------------------------------------------------------------------

DIM_QTYPE = "qtype"
DIM_DIFFICULTY = "difficulty"
DIM_SUB_TYPE = "sub_type"
DIM_YEAR = "year"

# ★ 固定的级联顺序，同时也是 slice_key 的拼接顺序和 depth 的取值依据。
#   题型和难度是严格划分（不重叠），优先用；年份排最后是因为一道题会出现在
#   多个年份的试卷里，按年份切出来的片之间有约 1.6 倍的重叠
DIM_ORDER: Tuple[str, ...] = (DIM_QTYPE, DIM_DIFFICULTY, DIM_SUB_TYPE, DIM_YEAR)


@dataclass(frozen=True)
class SliceValue:
    """切片维度上的一个取值"""

    code: str  # 短码，进 slice_key，如 t1
    name: str  # 人话名字，进 slice_name，如 单选题
    url_code: str  # 拼 URL 用的站点码，如 qt1101
    db_value: str  # recount 时用来过滤 questions 的值，如 1101


_QTYPE_VALUES: Tuple[SliceValue, ...] = (
    SliceValue("t1", "单选题", "qt1101", "1101"),
    SliceValue("t2", "多选题", "qt1104", "1104"),
    SliceValue("t3", "填空题", "qt1102", "1102"),
    SliceValue("t4", "解答题", "qt1103", "1103"),
    SliceValue("t5", "判断题", "qt1105", "1105"),
)

# 站点的难度筛选是 3 档，对应库里由得分率重算的 difficulty_band
_DIFFICULTY_VALUES: Tuple[SliceValue, ...] = (
    SliceValue("d1", "容易", "d1", "容易"),
    SliceValue("d2", "适中", "d2", "适中"),
    SliceValue("d3", "困难", "d3", "困难"),
)

# ★ 只有"题型=解答题"才有这一维，其它题型下面根本没有这个筛选项
_SUB_TYPE_VALUES: Tuple[SliceValue, ...] = (
    SliceValue("s1", "计算题", "01", "计算题"),
    SliceValue("s2", "作图题", "02", "作图题"),
    SliceValue("s3", "应用题", "03", "应用题"),
    SliceValue("s4", "证明题", "04", "证明题"),
    SliceValue("s5", "问答题", "05", "问答题"),
)

# 站点每年会多出一档。写死到 2026 会在明年悄悄少切一片（新题全落在没覆盖到的
# 那一年里），所以按当前年份动态生成，同时保一个下限不让它往回缩
_LATEST_YEAR = max(2026, date.today().year)
_YEAR_VALUES: Tuple[SliceValue, ...] = tuple(
    SliceValue(f"y{year}", f"{year}年", f"y{year}", str(year))
    for year in range(EARLIEST_YEAR, _LATEST_YEAR + 1)
) + (SliceValue("y-1", "更早以前", "y-1", "-1"),)


DIM_VALUES: Dict[str, Tuple[SliceValue, ...]] = {
    DIM_QTYPE: _QTYPE_VALUES,
    DIM_DIFFICULTY: _DIFFICULTY_VALUES,
    DIM_SUB_TYPE: _SUB_TYPE_VALUES,
    DIM_YEAR: _YEAR_VALUES,
}

_CODE_INDEX: Dict[str, Dict[str, SliceValue]] = {
    dim: {value.code: value for value in values} for dim, values in DIM_VALUES.items()
}

# 解答题的短码 —— 只有它底下才有子题型这一维
QTYPE_CODE_WITH_SUB_TYPE = "t4"

SLICE_KEY_RE = re.compile(
    r"^(?P<qtype>t[1-9])?(?P<difficulty>d[1-9])?(?P<sub_type>s[1-9])?"
    r"(?P<year>y(?:-1|\d{4}))?$"
)


class SliceOutcome(str, Enum):
    """处理完一片（或一个不带筛选条件的知识点）之后的结果"""

    DONE = "done"  # 按页码覆盖规则翻完了
    EMPTY = "empty"  # 站点说这一片没题
    NEED_SLICE = "need_slice"  # 超过硬顶，翻页拿不全，要往下切
    CAPPED = "capped"  # 四个维度都用完了还是超硬顶，终止状态
    INTERRUPTED = "partial"  # 半路停了（读不到页面/达到本次预算），保留未完成状态


def dim_depth(dim: str) -> int:
    """维度在级联里的序号，直接就是 knowledge_slice.depth。

    ★ 用的是"维度序号"而不是"实际切了几层"：单选题跳过了子题型这一维，
      它底下的年份片 depth 仍然是 4。线上 407 行历史数据就是这个口径。
    """
    return DIM_ORDER.index(dim) + 1


def next_dim(parts: Dict[str, str]) -> Optional[str]:
    """在当前筛选条件下，找下一个可以用来切片的维度；四维用尽返回 None。

    某一维在当前条件下没有可选值时要**跳过去找下一个**，不能因为"这一维不存在"
    就判定切不动了 —— 单选题没有子题型，但它还可以按年份切。
    """
    for dim in DIM_ORDER:
        if dim in parts:
            continue
        if dim == DIM_SUB_TYPE and parts.get(DIM_QTYPE) != QTYPE_CODE_WITH_SUB_TYPE:
            continue
        return dim
    return None


def current_dim(parts: Dict[str, str]) -> Optional[str]:
    """这一片是按哪一维切出来的（即 parts 里最深的那一维）"""
    for dim in reversed(DIM_ORDER):
        if dim in parts:
            return dim
    return None


def slice_key(parts: Dict[str, str]) -> str:
    """把筛选条件拼成 slice_key，顺序固定按 DIM_ORDER"""
    return "".join(parts[dim] for dim in DIM_ORDER if dim in parts)


def slice_name(parts: Dict[str, str]) -> str:
    """人话名字，如「解答题·容易·计算题」"""
    return "·".join(
        _CODE_INDEX[dim][parts[dim]].name for dim in DIM_ORDER if dim in parts
    )


def parse_slice_key(key: str) -> Dict[str, str]:
    """把 t4d1s1 还原成 {qtype: 't4', difficulty: 'd1', sub_type: 's1'}"""
    matched = SLICE_KEY_RE.match(key or "")
    if not matched:
        raise ValueError(f"无法解析的 slice_key: {key!r}")
    parts: Dict[str, str] = {}
    for dim, code in matched.groupdict().items():
        if not code:
            continue
        if code not in _CODE_INDEX[dim]:
            raise ValueError(f"slice_key {key!r} 里 {dim} 的取值 {code!r} 不认识")
        parts[dim] = code
    return parts


def slice_value(dim: str, code: str) -> SliceValue:
    return _CODE_INDEX[dim][code]


def url_filter_segment(parts: Dict[str, str]) -> str:
    """把筛选条件翻译成 URL 里那一段无分隔符的筛选码"""
    if DIM_SUB_TYPE in parts and DIM_QTYPE not in parts:
        # 子题型是接在题型码后面的两位数字，脱离题型无法单独表达
        raise ValueError("子题型必须依附于题型，不能单独出现在 URL 里")

    segment = ""
    qtype_code = parts.get(DIM_QTYPE)
    if qtype_code:
        segment += _CODE_INDEX[DIM_QTYPE][qtype_code].url_code
        sub_type_code = parts.get(DIM_SUB_TYPE)
        if sub_type_code:
            segment += _CODE_INDEX[DIM_SUB_TYPE][sub_type_code].url_code
    for dim in (DIM_DIFFICULTY, DIM_YEAR):
        code = parts.get(dim)
        if code:
            segment += _CODE_INDEX[dim][code].url_code
    return segment


def build_list_url(
    knowledge_id: str,
    parts: Optional[Dict[str, str]] = None,
    prefix: str = "czsx",
    order: str = "o2",
) -> str:
    """拼一个知识点（可带筛选条件）的列表页首页 URL。

    形如 https://zujuan.xkw.com/czsx/zsd4718/qt1103d1o2/ —— 结尾保留斜杠，
    和站点分页器给出的链接、以及库里已有的 list_url 保持同一种写法。
    """
    segment = url_filter_segment(parts or {})
    return f"{ZUJUAN_HOST}/{prefix}/{knowledge_id}/{segment}{order}/"


# 列表页 URL 的反解。人工翻页模式下，脚本唯一知道"这一页是什么"的途径就是
# 读浏览器地址栏 —— 所以这个正则必须和 build_list_url() 严格互为逆运算
LIST_URL_RE = re.compile(
    r"^https?://zujuan\.xkw\.com/(?P<prefix>[a-z]+)/(?P<knowledge_id>zsd\d+)/"
    r"(?P<filters>(?:qt\d{4,6})?(?:d\d)?(?:y(?:-1|\d{4}))?)"
    r"o(?P<order>\d+)(?:p(?P<page>\d+))?/?$"
)


@dataclass(frozen=True)
class ParsedListUrl:
    """从一个列表页 URL 反解出来的东西"""

    knowledge_id: str
    parts: Dict[str, str]
    page: int
    prefix: str

    @property
    def slice_key(self) -> str:
        return slice_key(self.parts)


def parse_url_filter_segment(segment: str) -> Dict[str, str]:
    """``url_filter_segment()`` 的逆运算：qt110305d1 -> {qtype:t4, sub_type:s5, difficulty:d1}"""
    parts: Dict[str, str] = {}
    rest = segment or ""

    matched = re.match(r"^qt(\d{4})(\d{2})?", rest)
    if matched:
        site_code, sub_code = matched.group(1), matched.group(2)
        for value in DIM_VALUES[DIM_QTYPE]:
            if value.url_code == f"qt{site_code}":
                parts[DIM_QTYPE] = value.code
                break
        if sub_code:
            for value in DIM_VALUES[DIM_SUB_TYPE]:
                if value.url_code == sub_code:
                    parts[DIM_SUB_TYPE] = value.code
                    break
        rest = rest[matched.end():]

    matched = re.match(r"^d(\d)", rest)
    if matched:
        code = f"d{matched.group(1)}"
        if code in _CODE_INDEX[DIM_DIFFICULTY]:
            parts[DIM_DIFFICULTY] = code
        rest = rest[matched.end():]

    matched = re.match(r"^y(-1|\d{4})", rest)
    if matched:
        code = f"y{matched.group(1)}"
        if code in _CODE_INDEX[DIM_YEAR]:
            parts[DIM_YEAR] = code
    return parts


def parse_list_url(url: str) -> Optional[ParsedListUrl]:
    """
    从浏览器地址栏反解出「哪个知识点 / 哪一片 / 第几页」，认不出返回 None。

    ★ 认不出时必须返回 None 而不是猜一个：人工翻页模式下这是唯一的归属依据，
      归错了会把 A 知识点的进度记到 B 头上。
    """
    matched = LIST_URL_RE.match((url or "").strip())
    if not matched:
        return None
    page_raw = matched.group("page")
    return ParsedListUrl(
        knowledge_id=matched.group("knowledge_id"),
        parts=parse_url_filter_segment(matched.group("filters")),
        page=int(page_raw) if page_raw else 1,
        prefix=matched.group("prefix"),
    )


def total_pages(site_total: int, page_size: int = PAGE_SIZE, max_page: int = MAX_PAGE) -> int:
    """这一片按站点报的题数应该有多少页，封顶到翻页硬顶"""
    if site_total <= 0:
        return 0
    return min(max_page, -(-site_total // page_size))


def exceeds_hard_cap(site_total: Optional[int]) -> bool:
    return site_total is not None and site_total > HARD_CAP


# ---------------------------------------------------------------------------
# 页码区间：covered_pages 的解析与合并
# ---------------------------------------------------------------------------
#
# 库里同时存着 last_page 和 covered_pages 两套进度表示，历史数据里它们会打架：
# zsd5930 的 last_page=317 但 covered_pages='1-281'。按 last_page+1=318 续采
# 会**静默跳过 282~317 这 36 页**，而且再也不会回头补。所以续采起点一律取
# covered_pages 的第一个缺口，只有 covered_pages 为空时才退回 last_page+1。


def is_fully_covered(spec: Optional[str], site_total: Optional[int]) -> bool:
    """
    按页码覆盖规则判断这一片是不是采完了。

    ★ 判据是"该翻的页都翻过了"，不是"库里的数够了" —— 站点会随时新增题，
      拿 collected >= site_total 当完成条件，永远差最后那几道就判不完。
      超过翻页硬顶的片不可能靠翻页覆盖完，一律返回 False。
    """
    if not site_total or site_total <= 0:
        return False
    if site_total > HARD_CAP:
        return False
    return first_uncovered_page(spec) > total_pages(site_total)


def parse_page_ranges(spec: Optional[str]) -> List[Tuple[int, int]]:
    """把 "1-40,88-120,300" 解析成 [(1, 40), (88, 120), (300, 300)]"""
    ranges: List[Tuple[int, int]] = []
    for chunk in (spec or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo_raw, _, hi_raw = chunk.partition("-")
            lo_raw, hi_raw = lo_raw.strip(), hi_raw.strip()
        else:
            lo_raw = hi_raw = chunk
        if not lo_raw.isdigit() or not hi_raw.isdigit():
            # 认不出来的片段直接丢掉：宁可少认一段（下次重采几页），
            # 也不能瞎猜成一个更大的区间把没采过的页当成采过了
            continue
        lo, hi = int(lo_raw), int(hi_raw)
        if lo > hi:
            lo, hi = hi, lo
        ranges.append((lo, hi))
    return merge_page_ranges(ranges)


def merge_page_ranges(ranges: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """排序并合并相邻/重叠的区间"""
    merged: List[Tuple[int, int]] = []
    for lo, hi in sorted(ranges):
        if merged and lo <= merged[-1][1] + 1:
            prev_lo, prev_hi = merged[-1]
            merged[-1] = (prev_lo, max(prev_hi, hi))
        else:
            merged.append((lo, hi))
    return merged


def expand_page_ranges(ranges: Sequence[Tuple[int, int]]) -> List[int]:
    """把区间摊成逐页的页码列表，超过翻页硬顶的页码直接丢掉。

    丢弃是有意的：第 999 页之后的页码不可能真实存在，一旦库里出现脏值
    （比如手工写了个 1-99999），展开出来就是几十万个数字撑爆这一列。
    """
    pages: List[int] = []
    for lo, hi in ranges:
        lo = max(1, lo)
        hi = min(hi, MAX_PAGE)
        if lo > hi:
            continue
        pages.extend(range(lo, hi + 1))
    return pages


def format_covered_pages(ranges: Sequence[Tuple[int, int]]) -> str:
    """
    ``covered_pages`` 的写入格式：**逐页、逗号分隔**，如 ``1,2,3,5``。

    ★ 不用 ``1-3,5`` 这种区间压缩：补采时要一眼看出中间缺了哪几页，区间格式
      得先在脑子里展开才知道。代价可以接受 —— 翻页硬顶 999 页，最长也就
      3887 个字符，这一列是 TEXT（64KB）。
    """
    return ",".join(str(page) for page in expand_page_ranges(ranges))


def add_page(spec: Optional[str], page: int) -> str:
    """把刚翻完的一页并进 covered_pages"""
    ranges = parse_page_ranges(spec)
    ranges.append((page, page))
    return format_covered_pages(merge_page_ranges(ranges))


def missing_pages(spec: Optional[str], site_total: Optional[int]) -> List[int]:
    """按站点报的题数算出还有哪几页没采过，站点总数未知时返回空列表"""
    if not site_total or site_total <= 0:
        return []
    covered = set(expand_page_ranges(parse_page_ranges(spec)))
    return [page for page in range(1, total_pages(site_total) + 1) if page not in covered]


def first_uncovered_page(spec: Optional[str], last_page: int = 0) -> int:
    """续采起点：covered_pages 的第一个缺口；没有 covered_pages 才用 last_page + 1"""
    ranges = parse_page_ranges(spec)
    if not ranges:
        return max(1, (last_page or 0) + 1)
    page = 1
    for lo, hi in ranges:
        if page < lo:
            return page
        page = max(page, hi + 1)
    return page
