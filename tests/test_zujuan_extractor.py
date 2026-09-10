# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_zujuan_extractor.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网解析器单测：口径必须和原采集程序逐字段一致，见 docs/zujuan/题干解析规范.md
"""
import hashlib
import json

from media_platform.zujuan.help import (
    PageStatus,
    ZuJuanExtractor,
    build_page_url,
    difficulty_band,
    expand_year,
    image_key,
    is_challenge_page,
    page_status,
    parse_score_rate,
    parse_title_abbr,
    split_province_city,
    split_qtype,
    strip_position_no,
)

CARD_HTML = """
<div class=" tk-quest-item  quesroot  " questionindex="1" questionid="35238538" bankid="2">
  <div class="ques-additional">
    <div class="top-msg">
      <span class="addi-msg">
        <a href="/2p3367834.html" title="原始出处" class="addi-msg ques-src">21-22九年级下·内蒙古呼和浩特·期中</a>
      </span>
    </div>
    <div class="msg-box">
      <div class="left-msg">
        <span class="addi-info"><span class="info-cnt">解答题-计算题</span></span>
        <span class="addi-info"><span class="info-cnt">困难 (0.4)</span></span>
        <span class="tag">名校</span>
        <div class="knowledge-list">
          <a href="/czsx/zsd5249/" title="反比例函数与几何综合" class="knowledge-item">反比例函数与几何综合</a>
          <a href="/czsx/zsd5249/tre5-15091" title="问题解决能力" class="knowledge-item">问题解决能力</a>
        </div>
      </div>
    </div>
  </div>
  <div class="wrapper quesdiv">
    <div class="exam-item__cnt ">
      2 . 求解方程<img src="https://staticzujuan.xkw.com/quesimg/Upload/formula/abc123.png" alt="">，如图<img src="https://img.xkw.com/dksih/QBM/x.png?resizew=147" alt="">
    </div>
  </div>
  <div class="exam-item__info clearfix">
    <div class="info-msgs">
      <span class="no-bound" title="2026/08/03">2026/08/03</span>
      <span title="323次组卷">323次组卷</span>
      <span class="look-more-src"><div hidden="" class="more-src-links">
        <a href="/2p3410462.html" title="卷A全名" class="src-item">卷A</a>
        <a href="/2p3367834.html" title="卷B全名" class="src-item">卷B</a>
        <a href="/2p3410462.html" title="卷A全名" class="src-item">卷A</a>
      </div></span>
    </div>
    <div class="ctrl-box">
      <a data-btn-type="quesDetail" href="/2q35238538.html">详情</a>
      <a data-btn-type="quesAdd" quesid="35238538" childnum="3"
         questitle="  内蒙古呼和浩特市某校2021-2022学年九年级下学期期中数学试题  "
         categoryid="5124" categoryname="反比例函数" qyid="1103" qyname="解答题"
         qdid="4" qdname="较难" qdvalue="0.4"
         titleabbreviation="21-22九年级下—内蒙古呼和浩特—期中">加入试题篮</a>
    </div>
  </div>
</div>
"""

CHALLENGE_HTML = (
    '<html><head><script>var x = window["parm_0"];</script></head>'
    '<body onload="check()"><input name="parm_1"></body></html>'
)
CAPTCHA_HTML = (
    '<html><body><div id="nc-container"></div>'
    '<script src="//g.alicdn.com/AWSC/AWSC/awsc.js"></script>'
    "<p>请完成安全验证</p></body></html>"
)


def only_question():
    questions = ZuJuanExtractor().extract_questions(
        CARD_HTML, list_url="https://zujuan.xkw.com/czsx/zsd5249/o2", page=1
    )
    assert len(questions) == 1
    return questions[0]


# --------------------------------------------------------------------------
# 位置号剥离
# --------------------------------------------------------------------------


def test_strip_position_no():
    assert strip_position_no("1 . 完成一项工程") == "完成一项工程"
    assert strip_position_no("  10 ． 求解") == "求解"
    assert strip_position_no("7 、 计算") == "计算"


def test_strip_position_no_does_not_eat_decimals():
    # 数字和点两边都要有空白才剥 —— 宽松写法会把这句剥成 "14 是圆周率"
    assert strip_position_no("3.14 是圆周率") == "3.14 是圆周率"
    assert strip_position_no("2.5x+1>0 的解集是") == "2.5x+1>0 的解集是"


# --------------------------------------------------------------------------
# title_abbr 三段式
# --------------------------------------------------------------------------


def test_parse_title_abbr_full_form():
    got = parse_title_abbr("25-26七年级上—湖南湘潭—期中")
    assert got["school_year"] == "2025-2026"
    assert got["year"] == 2025
    assert got["grade_level"] == "七年级"
    assert got["term"] == "上学期"
    assert got["province"] == "湖南"
    assert got["province_code"] == "430000"
    assert got["city"] == "湘潭"
    assert got["source_type"] == "期中"


def test_parse_title_abbr_year_and_grade_only():
    got = parse_title_abbr("2022九年级—贵州黔西南—专题练习")
    assert got["year"] == 2022
    assert got["school_year"] is None
    assert got["grade_level"] == "九年级"
    assert got["term"] is None


def test_parse_title_abbr_year_only():
    got = parse_title_abbr("2022—浙江宁波—模拟预测")
    assert got["year"] == 2022
    assert got["grade_level"] is None
    assert got["source_type"] == "模拟预测"


def test_parse_title_abbr_accepts_display_separator():
    # 属性里是全角破折号，页面显示文字用中点，两种都要认
    assert parse_title_abbr("2022·浙江宁波·模拟预测")["city"] == "宁波"


def test_parse_title_abbr_empty_and_garbage():
    assert parse_title_abbr("")["year"] is None
    # 格式不认识也不能抛异常，能解出多少算多少
    assert parse_title_abbr("完全看不懂的串")["source_type"] is None


# --------------------------------------------------------------------------
# 省市最长前缀匹配
# --------------------------------------------------------------------------


def test_split_province_city_longest_prefix_wins():
    # "内蒙古" 必须整体命中，不能被更短的前缀先吃掉
    assert split_province_city("内蒙古呼和浩特") == ("内蒙古", "150000", "呼和浩特")
    assert split_province_city("黑龙江大庆") == ("黑龙江", "230000", "大庆")


def test_split_province_city_municipality_has_no_city():
    # 直辖市省即市，不编造市名
    for name, code in (("北京", "110000"), ("上海", "310000"), ("天津", "120000"), ("重庆", "500000")):
        assert split_province_city(name) == (name, code, None)
    assert split_province_city("上海")[2] is None


def test_split_province_city_province_equals_city_name():
    # "吉林吉林" 只写了省名时，剥完省份没剩下东西，city 留空而不是空串
    assert split_province_city("吉林") == ("吉林", "220000", None)
    assert split_province_city("吉林长春") == ("吉林", "220000", "长春")


def test_split_province_city_unknown_keeps_raw():
    # 匹配不到省份时不丢数据：province 留空，整串塞进 city
    assert split_province_city("火星基地") == (None, None, "火星基地")


def test_nationwide_has_no_area_code():
    assert split_province_city("全国") == ("全国", None, None)


def test_expand_year():
    assert expand_year("25") == 2025
    assert expand_year("59") == 2059
    assert expand_year("60") == 1960
    assert expand_year("2022") == 2022


# --------------------------------------------------------------------------
# 难度 / 题型
# --------------------------------------------------------------------------


def test_difficulty_band_boundaries():
    assert difficulty_band(0.95) == "容易"
    assert difficulty_band(0.81) == "容易"
    assert difficulty_band(0.8) == "适中"  # 边界归下一档
    assert difficulty_band(0.51) == "适中"
    assert difficulty_band(0.5) == "困难"
    assert difficulty_band(0.4) == "困难"
    assert difficulty_band(1.0) == "容易"


def test_difficulty_band_out_of_range_is_empty():
    for value in (None, 0, -0.1, 1.5):
        assert difficulty_band(value) is None


def test_parse_score_rate_keeps_zero_and_rejects_garbage():
    # 0 是合法得分率，不能当"没取到"
    assert parse_score_rate("0") == 0.0
    assert parse_score_rate("0.95") == 0.95
    # 转换失败留空，★不要塞 0
    assert parse_score_rate("") is None
    assert parse_score_rate("abc") is None


def test_split_qtype():
    assert split_qtype("解答题-计算题") == "计算题"
    assert split_qtype("多选题－3个答案") == "3个答案"
    assert split_qtype("单选题") is None
    assert split_qtype("") is None


def test_image_key_drops_query_and_extension():
    assert image_key(
        "https://staticzujuan.xkw.com/quesimg/Upload/formula/7f2beb91f10d.png?x=1"
    ) == "7f2beb91f10d"


# --------------------------------------------------------------------------
# 整卡片解析
# --------------------------------------------------------------------------


def test_extract_scalar_fields():
    q = only_question()
    assert q.question_id == "35238538"
    assert q.bank_id == "2"
    assert q.qtype_code == "1103"
    assert q.qtype == "解答题"
    # qtype_full 只在正文 info-cnt 里，按钮属性没有子类型 —— 每次都要读，不是兜底
    assert q.qtype_full == "解答题-计算题"
    assert q.qtype_sub == "计算题"
    assert q.difficulty == "较难"
    assert q.difficulty_code == "4"
    assert q.score_rate == 0.4
    # 页面文案写的是 3 档的"困难"，按钮 qdname 是 5 档的"较难"，两套都要留
    assert q.difficulty_band == "困难"
    assert q.category_id == "5124"
    assert q.category_name == "反比例函数"
    assert q.used_count == 323
    assert q.updated_hint == "2026/08/03"
    assert q.detail_url == "/2q35238538.html"
    assert q.sub_question_count == "3"
    assert q.source == "内蒙古呼和浩特市某校2021-2022学年九年级下学期期中数学试题"


def test_extract_stem_html_is_inner_and_stripped():
    q = only_question()
    # innerHTML，不含外层 <div class="exam-item__cnt">，且开头的 "2 . " 已剥掉
    assert not q.stem_html.startswith("<div")
    assert q.stem_html.startswith("求解方程")
    assert "abc123.png" in q.stem_html
    assert q.stem_status == "html_saved"
    assert q.stem_hash == hashlib.md5(q.stem_html.encode("utf-8")).hexdigest()


def test_extract_title_abbr_is_parsed():
    q = only_question()
    assert q.title_abbr == "21-22九年级下—内蒙古呼和浩特—期中"
    assert q.school_year == "2021-2022"
    assert q.year == 2021
    assert q.grade_level == "九年级"
    assert q.term == "下学期"
    assert q.province == "内蒙古"
    assert q.province_code == "150000"
    assert q.city == "呼和浩特"
    assert q.source_type == "期中"


def test_knowledge_keeps_duplicate_ability_tag():
    q = only_question()
    # 末尾的能力标签 href 是 /czsx/zsd5249/tre5-15091，抠出的 id 和第一条撞车。
    # 原始数组要如实保留（进 JSONL 和 knowledge_tags），去重是写关联表时才做
    assert [(k.id, k.name) for k in q.knowledge] == [
        ("zsd5249", "反比例函数与几何综合"),
        ("zsd5249", "问题解决能力"),
    ]
    assert q.knowledge_id == "zsd5249"
    assert json.loads(q.knowledge_tags) == ["反比例函数与几何综合", "问题解决能力"]


def test_sources_dedup_and_order():
    q = only_question()
    # 只从 more-src-links 收集，按 paper_id 去重，保持 DOM 顺序；
    # 顶部 ques-src 指向 3367834，但它不是 sources[0]
    assert [s.paper_id for s in q.sources] == ["3410462", "3367834"]
    assert q.sources[0].bank_id == "2"
    assert q.sources[0].title == "卷A全名"
    assert q.paper_id == "3410462"


def test_formulas_and_images_split_by_url():
    q = only_question()
    assert [f.img_key for f in q.formulas] == ["abc123"]
    # alt="" 读不到 LaTeX，留空而不是空串
    assert q.formulas[0].latex is None
    assert [i.url for i in q.images] == ["https://img.xkw.com/dksih/QBM/x.png?resizew=147"]


def test_tags_become_explicit_flags():
    q = only_question()
    assert q.tags == ["名校"]
    # 角标是"有没有"，没有就是明确的 0，不是留空
    assert q.is_famous_school == 1
    assert q.is_real_exam == 0


def test_missing_question_id_does_not_raise():
    # 抽不到 ID 不抛异常，返回 question_id=None 让调用方能统计
    html = CARD_HTML.replace('questionid="35238538"', 'questionid=""')
    questions = ZuJuanExtractor().extract_questions(html)
    assert len(questions) == 1
    assert questions[0].question_id is None
    assert questions[0].stem_html  # 其余字段照常解析


# --------------------------------------------------------------------------
# 翻页 / 风控页判定
# --------------------------------------------------------------------------


def test_build_page_url():
    base = "https://zujuan.xkw.com/czsx/zsd5249/o2"
    assert build_page_url(base, 1) == base
    assert build_page_url(base, 3) == "https://zujuan.xkw.com/czsx/zsd5249/o2p3/"
    assert build_page_url("https://zujuan.xkw.com/czsx/zsd5249/o2p3/", 5) == (
        "https://zujuan.xkw.com/czsx/zsd5249/o2p5/"
    )
    template = "https://zujuan.xkw.com/czsx/zsd5249/o2p{page}/"
    assert build_page_url(base, 7, template) == "https://zujuan.xkw.com/czsx/zsd5249/o2p7/"


def test_page_status_ok_wins_over_markers():
    assert page_status(CARD_HTML) is PageStatus.OK
    assert page_status(CARD_HTML + CHALLENGE_HTML) is PageStatus.OK


def test_page_status_js_challenge():
    assert page_status(CHALLENGE_HTML) is PageStatus.JS_CHALLENGE


def test_page_status_captcha():
    assert page_status(CAPTCHA_HTML) is PageStatus.CAPTCHA
    assert page_status("<html><body>滑动验证</body></html>") is PageStatus.CAPTCHA


def test_page_status_unknown():
    assert page_status("") is PageStatus.UNKNOWN
    assert page_status("<html><body><p>没有题目也没有拦截特征</p></body></html>") is PageStatus.UNKNOWN


def test_is_challenge_page():
    assert is_challenge_page(CHALLENGE_HTML)
    assert is_challenge_page("") is True
    assert not is_challenge_page(CARD_HTML)


# ---------------------------------------------------------------------------
# 真实分页器 DOM（2026-09 从线上页面取的）
# ---------------------------------------------------------------------------

import pathlib as _pathlib

REAL_PAGER = (
    _pathlib.Path(__file__).resolve().parent.parent
    / "media_platform" / "zujuan" / "test_data" / "zujuan_pager.html"
).read_text(encoding="utf-8")


def test_real_pager_current_page_comes_from_data_num():
    """当前页是 <a data-num="1" class="... active">，data-num 比解析文本可靠"""
    from media_platform.zujuan.help import current_page_from_pager

    assert current_page_from_pager(REAL_PAGER) == 1


def test_real_pager_site_total():
    assert ZuJuanExtractor().extract_site_total(REAL_PAGER) == 2415435


def test_real_pager_total_page_ignores_understated_lastid():
    """★ 这个页面 data-sum=2415435（24 万页）但 a#lastpage 的 lastid 只写 100。
    信 lastid 会在第 100 页判定"翻完了"，静默漏掉后面的题 —— 取较大的并封到硬顶"""
    assert ZuJuanExtractor().extract_total_page(REAL_PAGER) == 999


def test_real_pager_url_template():
    assert (
        ZuJuanExtractor().extract_page_url_template(REAL_PAGER)
        == "https://zujuan.xkw.com/czsx/zsd4677/o2p{page}/"
    )


def test_total_page_prefers_the_larger_of_two_sources():
    from media_platform.zujuan.help import ZuJuanExtractor as _E

    # lastid 大于算出来的页数时以 lastid 为准
    html = '<div class="tk-pager" data-sum="50" data-size="10"></div><a id="lastpage" lastid="9"></a>'
    assert _E().extract_total_page(html) == 9
    # 两个都没有时退回 1
    assert _E().extract_total_page("<div></div>") == 1
