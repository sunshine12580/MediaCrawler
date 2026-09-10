# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_zujuan_slicing.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网知识点切片逻辑的单元测试（docs/zujuan/知识点切片抓取规范.md）。

重点覆盖三类最容易悄悄出错、且错了不会报错的地方：

1. slice_key 短码 <-> URL 站点码的翻译（尤其解答题子题型是**粘在题型码后面的
   两位**，不是独立一段）
2. slice_key 的拼接顺序必须固定 —— 顺序一变，断点续采就查不到上次那一行，
   会把整个知识点从头再切一遍
3. covered_pages 的缺口计算 —— 线上有 last_page=317 但 covered_pages='1-281'
   的行，按 last_page+1 续采会静默跳过 36 页
"""
import pytest

from media_platform.zujuan import slicing


# ----------------------------- slice_key 与 URL -----------------------------

@pytest.mark.parametrize(
    "key, expect_segment",
    [
        ("", ""),
        ("t1", "qt1101"),
        ("t2", "qt1104"),
        ("t3", "qt1102"),
        ("t4", "qt1103"),
        ("t5", "qt1105"),
        ("t1d3", "qt1101d3"),
        # ★ 子题型是接在题型码后面的两位：qt1103 + 05
        ("t4d3s5", "qt110305d3"),
        ("t4d1s1", "qt110301d1"),
        ("t1d1y2020", "qt1101d1y2020"),
        ("t1d1y-1", "qt1101d1y-1"),
        ("t4d3s4y2020", "qt110304d3y2020"),
    ],
)
def test_url_filter_segment(key, expect_segment):
    """这批 URL 段全部来自库里 questions.list_url 真实出现过的值"""
    assert slicing.url_filter_segment(slicing.parse_slice_key(key)) == expect_segment


def test_build_list_url():
    assert (
        slicing.build_list_url("zsd4718")
        == "https://zujuan.xkw.com/czsx/zsd4718/o2/"
    )
    assert (
        slicing.build_list_url("zsd4774", slicing.parse_slice_key("t4d1"))
        == "https://zujuan.xkw.com/czsx/zsd4774/qt1103d1o2/"
    )
    assert (
        slicing.build_list_url("zsd4774", slicing.parse_slice_key("t1"), prefix="gzsx")
        == "https://zujuan.xkw.com/gzsx/zsd4774/qt1101o2/"
    )


def test_slice_key_order_is_fixed_not_insertion_order():
    """填写顺序不同也必须得到同一个 key，否则断点续采会查不到上次那一行"""
    a = {"year": "y2025", "qtype": "t4", "sub_type": "s5", "difficulty": "d3"}
    b = {"qtype": "t4", "difficulty": "d3", "sub_type": "s5", "year": "y2025"}
    assert slicing.slice_key(a) == slicing.slice_key(b) == "t4d3s5y2025"


def test_parse_slice_key_round_trip():
    for key in ("t1", "t1d2", "t4d1s1", "t1d1y2020", "t1d1y-1", "t4d3s5y2025"):
        assert slicing.slice_key(slicing.parse_slice_key(key)) == key


def test_parse_slice_key_rejects_garbage():
    with pytest.raises(ValueError):
        slicing.parse_slice_key("d1t1")  # 顺序错了
    with pytest.raises(ValueError):
        slicing.parse_slice_key("t9")  # 没有这一档题型


def test_sub_type_cannot_stand_alone_in_url():
    """子题型是题型码的后两位，脱离题型没法表达，必须报错而不是拼出个假 URL"""
    with pytest.raises(ValueError):
        slicing.url_filter_segment({"sub_type": "s1"})


def test_slice_name_chain():
    assert slicing.slice_name(slicing.parse_slice_key("t4d1")) == "解答题·容易"
    assert slicing.slice_name(slicing.parse_slice_key("t4d1s1")) == "解答题·容易·计算题"
    assert slicing.slice_name(slicing.parse_slice_key("t1d1y2020")) == "单选题·容易·2020年"
    assert slicing.slice_name(slicing.parse_slice_key("t1d1y-1")) == "单选题·容易·更早以前"


# ----------------------------- 级联下钻 -----------------------------

def test_next_dim_follows_fixed_order():
    assert slicing.next_dim({}) == slicing.DIM_QTYPE
    assert slicing.next_dim({"qtype": "t1"}) == slicing.DIM_DIFFICULTY


def test_next_dim_skips_sub_type_for_non_answer_questions():
    """★ 只有解答题才有子题型这一维；其它题型要跳过去找年份，不能判定'切不动了'"""
    assert slicing.next_dim({"qtype": "t1", "difficulty": "d1"}) == slicing.DIM_YEAR
    assert slicing.next_dim({"qtype": "t4", "difficulty": "d1"}) == slicing.DIM_SUB_TYPE


def test_next_dim_exhausted():
    assert slicing.next_dim({"qtype": "t1", "difficulty": "d1", "year": "y2020"}) is None
    assert (
        slicing.next_dim(
            {"qtype": "t4", "difficulty": "d1", "sub_type": "s1", "year": "y2020"}
        )
        is None
    )


def test_dim_depth_is_cascade_index_not_layer_count():
    """★ depth 存的是维度序号，不是'实际切了几层' —— 线上 407 行就是这个口径。
    单选题跳过了子题型，它底下的年份片仍然是 depth=4"""
    assert slicing.dim_depth(slicing.DIM_QTYPE) == 1
    assert slicing.dim_depth(slicing.DIM_DIFFICULTY) == 2
    assert slicing.dim_depth(slicing.DIM_SUB_TYPE) == 3
    assert slicing.dim_depth(slicing.DIM_YEAR) == 4

    parts = slicing.parse_slice_key("t1d1y2023")  # 只用了 3 个维度
    assert slicing.dim_depth(slicing.current_dim(parts)) == 4


def test_current_dim_is_the_deepest_one():
    assert slicing.current_dim({}) is None
    assert slicing.current_dim(slicing.parse_slice_key("t4d1")) == slicing.DIM_DIFFICULTY
    assert slicing.current_dim(slicing.parse_slice_key("t4d1s1")) == slicing.DIM_SUB_TYPE


def test_year_dimension_covers_2020_to_now_plus_earlier():
    codes = [value.code for value in slicing.DIM_VALUES[slicing.DIM_YEAR]]
    for year in range(2020, 2027):
        assert f"y{year}" in codes
    assert codes[-1] == "y-1"


# ----------------------------- 翻页硬顶 -----------------------------

def test_hard_cap_constants():
    assert slicing.MAX_PAGE == 999
    assert slicing.HARD_CAP == 9990


def test_total_pages_is_capped_at_hard_limit():
    assert slicing.total_pages(0) == 0
    assert slicing.total_pages(1) == 1
    assert slicing.total_pages(10) == 1
    assert slicing.total_pages(11) == 2
    assert slicing.total_pages(3834) == 384
    assert slicing.total_pages(9990) == 999
    # 再多也只能翻到 999 页
    assert slicing.total_pages(24003) == 999


def test_exceeds_hard_cap_treats_unknown_as_not_exceeding():
    assert slicing.exceeds_hard_cap(9991) is True
    assert slicing.exceeds_hard_cap(9990) is False
    # ★ None 是"读不到"，不是"超了"，调用方另有处置
    assert slicing.exceeds_hard_cap(None) is False


# ----------------------------- covered_pages -----------------------------

def test_parse_and_merge_page_ranges():
    assert slicing.parse_page_ranges("") == []
    assert slicing.parse_page_ranges(None) == []
    assert slicing.parse_page_ranges("1-40,88-120") == [(1, 40), (88, 120)]
    assert slicing.parse_page_ranges("300") == [(300, 300)]
    # 相邻区间要合并
    assert slicing.parse_page_ranges("1-40,41-50") == [(1, 50)]
    # 乱序、重叠都要归一
    assert slicing.parse_page_ranges("88-120,1-40,30-50") == [(1, 50), (88, 120)]


def test_parse_page_ranges_drops_garbage_instead_of_guessing():
    """认不出来的片段宁可丢掉（下次重采几页），也不能瞎猜成更大的区间"""
    assert slicing.parse_page_ranges("1-40,abc,88-120") == [(1, 40), (88, 120)]


def test_add_page_writes_every_page_number():
    """★ covered_pages 写成逐页逗号分隔，不做区间压缩 ——
    补采时要一眼看出中间缺了哪几页"""
    assert slicing.add_page(None, 1) == "1"
    assert slicing.add_page("1,2,3,7,8,9", 4) == "1,2,3,4,7,8,9"
    assert slicing.add_page("1,2,3,5,6", 4) == "1,2,3,4,5,6"
    # 重复写同一页不会写重
    assert slicing.add_page("1,2,3", 2) == "1,2,3"
    # 老数据里的区间格式照样读得懂，写回去时展开
    assert slicing.add_page("1-3", 5) == "1,2,3,5"


def test_covered_pages_never_exceeds_the_hard_cap():
    """脏值不能撑爆这一列：第 999 页之后的页码不可能存在，直接丢"""
    expanded = slicing.format_covered_pages(slicing.parse_page_ranges("998-99999"))
    assert expanded == "998,999"


def test_covered_pages_full_length_fits_in_the_column():
    """999 页全采满也就 3887 字符，TEXT 列（64KB）装得下"""
    full = slicing.format_covered_pages([(1, slicing.MAX_PAGE)])
    assert full.startswith("1,2,3,")
    assert full.endswith(",999")
    assert len(full) < 5000


def test_missing_pages_says_exactly_which_pages_are_left():
    # 25 道 = 3 页
    assert slicing.missing_pages("1,3", 25) == [2]
    assert slicing.missing_pages("1,2,3", 25) == []
    assert slicing.missing_pages(None, 25) == [1, 2, 3]
    # 老格式也认
    assert slicing.missing_pages("1-2", 25) == [3]
    # 站点总数未知时不猜
    assert slicing.missing_pages("1,2", None) == []


def test_first_uncovered_page_uses_the_gap_not_last_page():
    """★ 线上 zsd5930 就是 last_page=317 / covered_pages='1-281'。
    按 last_page+1=318 续采会静默跳过 282~317 这 36 页，而且再也不会回头补"""
    assert slicing.first_uncovered_page("1-281", 317) == 282
    assert slicing.first_uncovered_page("1-3", 3) == 4
    assert slicing.first_uncovered_page("1-40,88-120", 120) == 41
    # 没有 covered_pages 才退回 last_page + 1
    assert slicing.first_uncovered_page(None, 19) == 20
    assert slicing.first_uncovered_page("", 0) == 1


# ----------------------------- 列表页 URL 反解 -----------------------------
#
# 人工翻页模式下，脚本唯一知道"人现在在看哪个知识点的第几页"的途径就是读地址栏。
# 解错了会把 A 知识点的题和进度记到 B 头上，而且不报错。

@pytest.mark.parametrize(
    "url, knowledge_id, key, page, prefix",
    [
        ("https://zujuan.xkw.com/czsx/zsd5501/o2/", "zsd5501", "", 1, "czsx"),
        ("https://zujuan.xkw.com/czsx/zsd5501/o2", "zsd5501", "", 1, "czsx"),
        ("https://zujuan.xkw.com/czsx/zsd5501/o2p387/", "zsd5501", "", 387, "czsx"),
        ("https://zujuan.xkw.com/czsx/zsd4774/qt1103d1o2p387/", "zsd4774", "t4d1", 387, "czsx"),
        ("https://zujuan.xkw.com/czsx/zsd1/qt110305d1y-1o2p12/", "zsd1", "t4d1s5y-1", 12, "czsx"),
        ("https://zujuan.xkw.com/czsx/zsd1/qt1101d1y2020o2/", "zsd1", "t1d1y2020", 1, "czsx"),
        ("https://zujuan.xkw.com/gzsx/zsd28745/o2p3/", "zsd28745", "", 3, "gzsx"),
    ],
)
def test_parse_list_url(url, knowledge_id, key, page, prefix):
    parsed = slicing.parse_list_url(url)
    assert parsed is not None
    assert parsed.knowledge_id == knowledge_id
    assert parsed.slice_key == key
    assert parsed.page == page
    assert parsed.prefix == prefix


@pytest.mark.parametrize(
    "url",
    [
        "https://zujuan.xkw.com/",                       # 首页
        "https://zujuan.xkw.com/czsx/zsd5501/",          # 知识点页但不是列表页
        "https://zujuan.xkw.com/czsx/zsd5501/o2p12/x/",  # 多了一段
        "https://example.com/czsx/zsd1/o2/",             # 别的站
        "",
        None,
    ],
)
def test_parse_list_url_returns_none_instead_of_guessing(url):
    """★ 认不出必须返回 None。猜一个出来会把进度记到错误的知识点上，而且不报错"""
    assert slicing.parse_list_url(url) is None


def test_parse_list_url_round_trips_with_build_list_url():
    """反解和拼接必须严格互逆 —— 这套码表在 5000 条真实 list_url 上验过 0 差异"""
    from media_platform.zujuan.help import build_page_url

    for url in (
        "https://zujuan.xkw.com/czsx/zsd4774/qt1103d1o2p387/",
        "https://zujuan.xkw.com/czsx/zsd1/qt110305d1y-1o2p12/",
        "https://zujuan.xkw.com/czsx/zsd5501/o2p2/",
    ):
        parsed = slicing.parse_list_url(url)
        base = slicing.build_list_url(parsed.knowledge_id, parsed.parts, prefix=parsed.prefix)
        assert build_page_url(base, parsed.page, None) == url


def test_parse_url_filter_segment_is_inverse_of_builder():
    for key in ("", "t1", "t4d1", "t4d1s1", "t1d1y2020", "t4d3s5y2025", "t1d1y-1"):
        parts = slicing.parse_slice_key(key)
        segment = slicing.url_filter_segment(parts)
        assert slicing.parse_url_filter_segment(segment) == parts


# ----------------------------- 完成判定 -----------------------------

def test_is_fully_covered():
    """25 道 = 3 页，翻完 1-3 才算完"""
    assert slicing.is_fully_covered("1-3", 25) is True
    assert slicing.is_fully_covered("1-2", 25) is False
    assert slicing.is_fully_covered("1,3", 25) is False      # 中间缺一页
    assert slicing.is_fully_covered("1-5", 25) is True       # 多翻了也算完


def test_is_fully_covered_needs_a_known_total():
    """site_total 不知道就不能判完成 —— 否则会把没采的知识点标成 done"""
    assert slicing.is_fully_covered("1-3", None) is False
    assert slicing.is_fully_covered("1-3", 0) is False
    assert slicing.is_fully_covered(None, 25) is False


def test_is_fully_covered_never_true_beyond_hard_cap():
    """★ 超过硬顶的片翻页覆盖不完，不能因为翻到第 999 页就判成 done"""
    assert slicing.is_fully_covered("1-999", 24003) is False
    assert slicing.is_fully_covered("1-999", 9990) is True
