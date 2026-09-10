# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zujuan/help.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网列表页解析：卡片 HTML -> 结构化字段

算法严格遵循 docs/zujuan/题干解析规范.md，口径要和原采集程序逐字段一致。
几条不能改的纪律：

- 解析不出来的字段一律留 None，不要塞 "" / 0 —— 0 是合法得分率，空串会覆盖库里已有值
- 按钮 ``a[data-btn-type="quesAdd"]`` 上的属性优先于正文文字
- 题干开头的位置号必须剥掉（它是"本页第几题"，同一道题换页码就变）
- 任何一个字段抽取失败都不许抛异常中断整道题
"""

import hashlib
import html as html_lib
import json
import re
from enum import Enum
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from parsel import Selector

from model.m_zujuan import (
    ZujuanFormula,
    ZujuanImage,
    ZujuanKnowledge,
    ZujuanQuestion,
    ZujuanSource,
)
from tools import utils

ZUJUAN_HOST = "https://zujuan.xkw.com"

# 翻页硬顶：第 999 页之后站点原样重复第 999 页（见 slicing.MAX_PAGE，
# 这里单独写一份避免 help -> slicing 的反向依赖）
MAX_PAGE = 999

# 正向白名单：出现其中任何一个就说明确实拿到了一个真实的列表页（优先级最高）。
#   tk-quest-item   —— 页面上有题目卡片
#   id="questioncount" —— "共计 N 道试题"那个元素。★ 必须有这一条：题量为 0 的
#     知识点页面上一张卡片都没有，只看卡片会和被 WAF 拦下的页面长得一模一样，
#     结果就是空知识点的 site_total 永远记不下来。WAF 的挑战页/验证页不会带这个 id
_CONTENT_MARKERS = ("tk-quest-item", 'id="questioncount"')

# 阿里云 WAF 的 JS 挑战页特征：会自动算 hash 写 Cookie 后 reload，浏览器可无感通过
_CHALLENGE_MARKERS = ("parm_0", "alicfw")

# 阿里云 WAF 人机验证（滑块/点选/无痕）的特征，必须由人来过
_CAPTCHA_MARKERS = (
    "nc-container",  # 阿里云验证码组件容器
    "nc_wrapper",
    "AWSC/AWSC/awsc.js",  # 阿里云安全验证 SDK
    "_____tmd_____",  # 阿里云 WAF 验证/拦截跳转路径
    "captcha-verify",
    "滑动验证",
    "拖动滑块",
    "安全验证",
)

# 题干开头的位置号，如 "1 . "。数字和点两边都必须有空白 ——
# 宽松写法（\d+\s*\.）会把 "3.14 是圆周率" 剥成 "14 是圆周率"，制造静默数据损坏
POSITION_NO_RE = re.compile(r"^\s*\d{1,3}\s+[.．、]\s+")

# 公式图的 URL 特征，除此之外的 <img> 都算插图
FORMULA_URL_MARK = "/Upload/formula/"

# 来源试卷链接 /2p3391141.html -> (bank_id=2, paper_id=3391141)
PAPER_HREF_RE = re.compile(r"/(\d+)p(\d+)\.html")

# 知识点链接 /czsx/zsd5249/ -> zsd5249
KNOWLEDGE_ID_RE = re.compile(r"(zsd\d+)")

USED_COUNT_RE = re.compile(r"(\d+)\s*次组卷")

# title_abbr 的分隔符：属性里是全角破折号，页面显示文字用中点，两种都认
TITLE_ABBR_SEP_RE = re.compile(r"[—·]")

# 题型子类型的分隔符
QTYPE_SEP_RE = re.compile(r"[-－—]")

# title_abbr 第 1 段：学年区间 / 四位年份 + 年级 + 学期，三种形态都要能处理
SEG_SCHOOL_RE = re.compile(
    r"^\s*(?:(?P<y1>\d{2,4})\s*-\s*(?P<y2>\d{2,4})|(?P<y>\d{4}))?"
    r"\s*(?P<grade>[一二三四五六七八九十]+年级)?"
    r"\s*(?P<term>[上下])?\s*$"
)

# 从来源试卷全名里兜底抠年份
YEAR_FALLBACK_RE = re.compile(r"(20\d{2})")

# 省级行政区 -> GB/T 2260 码。"全国" 是站点的特殊取值，没有行政区划码。
# 用的时候必须按名称长度降序匹配，否则 "内蒙古" 会被更短的名字先吃掉。
PROVINCE_CODES: Dict[str, Optional[str]] = {
    "北京": "110000", "天津": "120000", "河北": "130000", "山西": "140000",
    "内蒙古": "150000", "辽宁": "210000", "吉林": "220000", "黑龙江": "230000",
    "上海": "310000", "江苏": "320000", "浙江": "330000", "安徽": "340000",
    "福建": "350000", "江西": "360000", "山东": "370000", "河南": "410000",
    "湖北": "420000", "湖南": "430000", "广东": "440000", "广西": "450000",
    "海南": "460000", "重庆": "500000", "四川": "510000", "贵州": "520000",
    "云南": "530000", "西藏": "540000", "陕西": "610000", "甘肃": "620000",
    "青海": "630000", "宁夏": "640000", "新疆": "650000", "全国": None,
}

# 最长前缀匹配用的省份名列表，按长度降序
_PROVINCE_NAMES = sorted(PROVINCE_CODES, key=len, reverse=True)

# 直辖市：省即市，city 留空，不编造市名
_MUNICIPALITIES = frozenset({"北京", "上海", "天津", "重庆"})


class PageStatus(str, Enum):
    """一次页面请求的结果分级，决定后续如何处置"""

    OK = "ok"  # 拿到了目标数据
    JS_CHALLENGE = "js_challenge"  # JS 挑战页，浏览器可自动通过
    CAPTCHA = "captcha"  # 人机验证，需要人工介入
    UNKNOWN = "unknown"  # 认不出来 —— 一律当失败处理，绝不当成空数据


def page_status(page_html: str) -> PageStatus:
    """
    判断页面处于风控阶梯的哪一层。

    注意顺序：先用"有没有目标数据"正向确认成功，剩下的才逐层匹配拦截特征。
    人机验证页同样返回 HTTP 200，不检测就会被当成空页静默写入空数据。
    """
    if not page_html:
        return PageStatus.UNKNOWN
    if any(marker in page_html for marker in _CONTENT_MARKERS):
        return PageStatus.OK
    if any(marker in page_html for marker in _CAPTCHA_MARKERS):
        return PageStatus.CAPTCHA
    if any(marker in page_html for marker in _CHALLENGE_MARKERS):
        return PageStatus.JS_CHALLENGE
    return PageStatus.UNKNOWN


def is_challenge_page(page_html: str) -> bool:
    """页面是否没能拿到目标数据（挑战页、人机验证页或认不出来的页面）"""
    return page_status(page_html) is not PageStatus.OK


QUESTION_ID_RE = re.compile(r'questionid="(\d+)"')

# 分页器里"当前页"的读法。真实结构是
#   <a data-num="1" data-type="switchPage" class="pager-item page-num active">1</a>
# data-num 是权威的（页码就在属性里，不用解析文本），文本兜底应对改版。
# 都认不出时 current_page_from_pager() 返回 None，调用方会退回直接 goto
_CURRENT_PAGE_ATTR_SELECTORS = (
    'div.tk-pager a[data-type="switchPage"].active::attr(data-num)',
    "div.tk-pager a.pager-item.active::attr(data-num)",
    "div.tk-pager .active::attr(data-num)",
)
_CURRENT_PAGE_TEXT_SELECTORS = (
    "div.tk-pager a.active::text",
    "div.tk-pager li.active a::text",
    "div.tk-pager a.current::text",
    "div.tk-pager span.current::text",
)


def first_question_id(page_html: str) -> Optional[str]:
    """当前页第一张卡片的 question_id，用来判断点击翻页之后内容有没有真的换掉"""
    matched = QUESTION_ID_RE.search(page_html or "")
    return matched.group(1) if matched else None


def current_page_from_pager(page_html: str) -> Optional[int]:
    """
    从分页器里读"现在显示的是第几页"，读不出来返回 None。

    ★ 这是点击翻页唯一可靠的校验手段。站点的翻页链接是 data-type="switchPage"
      的 JS 链接，点完 URL 可能根本不变，光看"内容换了"没法确认换到的是不是
      目标页 —— 点错一个链接就会把别的页的题当成第 N 页入库并记进度，属于不报错
      的静默数据损坏。宁可确认不了就退回 goto。
    """
    selector = Selector(page_html or "")
    for css in _CURRENT_PAGE_ATTR_SELECTORS + _CURRENT_PAGE_TEXT_SELECTORS:
        for text in selector.css(css).getall():
            text = (text or "").strip()
            if text.isdigit():
                return int(text)
    return None


def dump_pager_html(page_html: str, limit: int = 1500) -> str:
    """把分页器那一段原样抠出来，认不出结构时打进日志好让人贴回来看"""
    pager = Selector(page_html or "").css("div.tk-pager").get()
    if not pager:
        return "<没有找到 div.tk-pager>"
    pager = re.sub(r"\s+", " ", pager).strip()
    return pager[:limit] + ("…" if len(pager) > limit else "")


def build_page_url(list_url: str, page: int, page_url_template: Optional[str] = None) -> str:
    """
    拼接列表页翻页 URL。

    组卷网的翻页形如 /czsx/zsd5249/o2 -> /czsx/zsd5249/o2p2/，
    优先使用页面分页器里自带的 data-href 作为模板，拿不到时按规则拼。
    """
    if page <= 1:
        return list_url

    if page_url_template:
        return page_url_template.replace("{page}", str(page))

    parsed = urlparse(list_url)
    path = re.sub(r"p\d+$", "", parsed.path.rstrip("/")).rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}p{page}/"


def strip_position_no(text: str) -> str:
    """
    剥掉题干开头的位置号。

    这个序号是"这张卡片在当前列表页上排第几"（一页 10 道就是 1~10），
    同一道题挂在不同知识点、出现在不同页码时每次都不一样。不剥掉的话
    stem_hash 每次都会变，重复抓取判重直接失效。
    """
    if not text:
        return ""
    return POSITION_NO_RE.sub("", text, count=1).strip()


def expand_year(value: str) -> int:
    """两位年份补成四位：< 60 当 2000+，>= 60 当 1900+"""
    num = int(value)
    if len(value) >= 4:
        return num
    return 2000 + num if num < 60 else 1900 + num


def split_province_city(segment: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    把 "湖南湘潭" 这样省市连写的串切成 (省, 省码, 市)。

    省市之间没有任何分隔符，只能靠省份表做最长前缀匹配。匹配不到省份时
    province 留空、city 存整串 —— 不丢数据，也不编造。
    """
    text = (segment or "").strip()
    if not text:
        return None, None, None

    for name in _PROVINCE_NAMES:
        if not text.startswith(name):
            continue
        code = PROVINCE_CODES[name]
        if name in _MUNICIPALITIES:
            # 直辖市省即市，不编造市名
            return name, code, None
        city = text[len(name):].strip()
        return name, code, city or None

    return None, None, text


def parse_title_abbr(title_abbr: str) -> Dict[str, Optional[object]]:
    """
    拆解三段式简称，如 "25-26七年级上—湖南湘潭—期中"。

    从右往左理解：第 3 段是来源类型、第 2 段是省市、第 1 段是学年+年级+学期。
    每段都可能缺失，缺哪段就留空哪些字段，绝不因为格式不符就整题失败。
    """
    result: Dict[str, Optional[object]] = {
        "school_year": None, "year": None, "grade_level": None, "term": None,
        "province": None, "province_code": None, "city": None, "source_type": None,
    }
    if not title_abbr:
        return result

    segments = [s.strip() for s in TITLE_ABBR_SEP_RE.split(title_abbr.strip())]

    # 第 3 段：来源类型。词表比筛选下拉框里的选项多，原样存字符串，不做校验
    if len(segments) >= 3 and segments[2]:
        result["source_type"] = segments[2]

    # 第 2 段：省 + 市
    if len(segments) >= 2:
        province, code, city = split_province_city(segments[1])
        result["province"], result["province_code"], result["city"] = province, code, city

    # 第 1 段：学年 + 年级 + 学期
    if segments and segments[0]:
        match = SEG_SCHOOL_RE.match(segments[0])
        if match:
            y1, y2, y = match.group("y1"), match.group("y2"), match.group("y")
            if y1 and y2:
                start, end = expand_year(y1), expand_year(y2)
                result["school_year"] = f"{start}-{end}"
                result["year"] = start
            elif y:
                result["year"] = int(y)
            if match.group("grade"):
                result["grade_level"] = match.group("grade")
            if match.group("term"):
                result["term"] = f"{match.group('term')}学期"

    return result


def split_qtype(qtype_full: str) -> Optional[str]:
    """
    从完整题型里拆出子类型：'解答题-计算题' -> '计算题'。

    只有解答题和多选题会拆出东西，其余题型没有横线，返回 None。
    """
    if not qtype_full:
        return None
    parts = [p.strip() for p in QTYPE_SEP_RE.split(qtype_full)]
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return None


def difficulty_band(score_rate: Optional[float]) -> Optional[str]:
    """
    按得分率重算 3 档难度。

    ★ 这一档和 difficulty_code/difficulty 的 5 档是完全独立的两套编码，数字会撞车，
    绝对不能混用：卡片的 qdid=2 是"较易"，而 3 档编码里的 2 是"适中"。
    """
    if score_rate is None or not (0 < score_rate <= 1):
        return None
    if score_rate > 0.8:
        return "容易"
    if score_rate > 0.5:
        return "适中"
    return "困难"


def parse_score_rate(raw: str) -> Optional[float]:
    """qdvalue -> float。转换失败留空，★不要塞 0 —— 0 是合法得分率"""
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def image_key(url: str) -> str:
    """
    公式图 URL 的去重键：去掉查询参数后的文件名（不含扩展名）。

    公式图的文件名本身就是站点算好的内容哈希，同一个公式在哪道题里 URL 都一样，
    天然就是去重键，不用下载图片再算一遍。
    """
    name = urlparse(url or "").path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def md5_hex(text: str) -> Optional[str]:
    """题干 HTML 的 md5，用于重复抓取时判重"""
    if not text:
        return None
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _clean_text(raw_html: str) -> str:
    """去标签 + 还原实体 + 压缩空白，只用于日志预览和取组卷次数这类短文本"""
    if not raw_html:
        return ""
    text = html_lib.unescape(utils.extract_text_from_html(raw_html))
    return re.sub(r"[ \t　]*\n[\s\n]*", "\n", re.sub(r"[ \t ]+", " ", text)).strip()


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    """空串一律转成 None —— 解析不出来就是没有值，不是空字符串"""
    if value is None:
        return None
    value = value.strip()
    return value or None


class ZuJuanExtractor:
    """组卷网页面解析器：列表页 HTML -> 题目结构化数据"""

    def extract_page_url_template(self, page_html: str) -> Optional[str]:
        """
        从分页器里取一个真实的翻页链接作为模板，把页码替换成 {page}
        例：/czsx/zsd5249/o2p2/ -> https://zujuan.xkw.com/czsx/zsd5249/o2p{page}/
        """
        selector = Selector(page_html)
        for href in selector.css('a[data-type="switchPage"]::attr(data-href)').getall():
            href = href.strip()
            if not href or not re.search(r"p\d+/?$", href):
                continue
            template = re.sub(r"p\d+(/?)$", r"p{page}\1", href)
            return urljoin(ZUJUAN_HOST, template)
        return None

    def extract_total_page(self, page_html: str) -> int:
        """
        从分页器推断总页数，拿不到时返回 1。

        ★ 以 data-sum / data-size 算出来的为准，a#lastpage 的 lastid 只当兜底。
          实测 lastid 会**严重少报**：某个 data-sum=2415435（24 万页）的页面上
          lastid 只写 100，而库里存在 last_page=991 的记录，说明 100 页之后照样
          能翻。信了 lastid 就会在第 100 页判定"翻完了"，静默漏掉后面的题。
          两个来源都有时取较大的：多翻一页顶多发现没卡片就停，少翻则是丢数据。
        """
        selector = Selector(page_html)
        candidates = []

        pager = selector.css("div.tk-pager")
        if pager:
            total = pager.attrib.get("data-sum")
            size = pager.attrib.get("data-size")
            if total and size and total.isdigit() and size.isdigit() and int(size) > 0:
                candidates.append(-(-int(total) // int(size)))

        last_id = selector.css("a#lastpage::attr(lastid)").get()
        if last_id and last_id.isdigit():
            candidates.append(int(last_id))

        if not candidates:
            return 1
        # 翻页硬顶封住，再大的数也翻不过去
        return max(1, min(max(candidates), MAX_PAGE))

    def extract_site_total(self, page_html: str) -> Optional[int]:
        """
        列表页声明的"共计 N 道试题"，读不到返回 None。

        ★ 返回 None 和返回 0 是两回事：0 是站点明说这里没题，None 是连这个数字
          都没读到 —— 正常列表页哪怕这一页没卡片，这个数字也应该在，读不到说明
          打开的多半不是一个正常列表页（被拦截、或者页面结构变了）。调用方必须
          保留"还没翻完"的状态下次重试，误判成"翻完了"的代价是这个知识点后面
          的题永远不会再被采集。
        """
        selector = Selector(page_html)
        # 带筛选条件时这里显示的就是这一片的数，是切片判断的唯一依据
        raw = selector.css("#questioncount::text").get()
        if raw:
            digits = re.sub(r"[^\d]", "", raw)
            if digits:
                return int(digits)

        pager = selector.css("div.tk-pager")
        if pager:
            total = pager.attrib.get("data-sum")
            if total and total.isdigit():
                return int(total)
        return None

    def extract_total_question_count(self, page_html: str) -> int:
        """列表页声明的题目总数，拿不到时返回 0（不区分"没题"和"没读到"的旧接口）"""
        total = self.extract_site_total(page_html)
        return total if total is not None else 0

    def extract_questions(self, page_html: str, list_url: str = "", page: int = 1) -> List[ZujuanQuestion]:
        """
        解析列表页里的全部题目。

        单道题解析失败只丢这一道，不能拖累同页其它 9 道。
        """
        selector = Selector(page_html)
        questions: List[ZujuanQuestion] = []
        for item in selector.css("div.tk-quest-item"):
            try:
                question = self._extract_one_question(item, list_url=list_url, page=page)
            except Exception as e:  # noqa: BLE001 - 单题失败不能中断整页
                utils.logger.error(f"[ZuJuanExtractor.extract_questions] 解析单题失败: {e}")
                continue
            if question is not None:
                questions.append(question)
        return questions

    def _extract_one_question(self, item: Selector, list_url: str, page: int) -> Optional[ZujuanQuestion]:
        # 抽不到 question_id 也不抛异常，返回 question_id=None 让调用方能统计
        # "这一页 10 张卡片里有几张没 ID" —— 这类故障不报错，只是数量悄悄变少
        question_id = _blank_to_none(item.attrib.get("questionid"))

        # "加入试题篮"按钮上挂着绝大多数结构化字段，优先级高于任何正文文字。
        # ★这是个真按钮，只读属性，绝不能点击 —— 点了会真的把题目加入试题篮
        btn = item.css('a[data-btn-type="quesAdd"]')
        attrs: Dict[str, str] = btn.attrib if btn else {}

        # ---- 题干：取 innerHTML 并剥掉位置号 ----
        content_node = item.css("div.exam-item__cnt")
        inner_html = "".join(content_node[0].xpath("node()").getall()) if content_node else ""
        stem_html = strip_position_no(inner_html)

        # ---- 题型：qyname 只有大类，子类型只在正文第一个 info-cnt 里，每次都要读 ----
        info_texts = [
            text.strip()
            for text in item.css(".left-msg .addi-info .info-cnt::text").getall()
            if text.strip()
        ]
        qtype_full = _blank_to_none(info_texts[0] if info_texts else None)
        qtype = _blank_to_none(attrs.get("qyname")) or (
            QTYPE_SEP_RE.split(qtype_full)[0].strip() if qtype_full else None
        )

        # ---- 难度：5 档来自按钮，3 档由得分率重算 ----
        score_rate = parse_score_rate(attrs.get("qdvalue", ""))

        # ---- 三段式简称 ----
        title_abbr = _blank_to_none(attrs.get("titleabbreviation"))
        abbr = parse_title_abbr(title_abbr or "")

        source_full = _blank_to_none(attrs.get("questitle"))
        year = abbr["year"]
        if year is None and source_full:
            matched = YEAR_FALLBACK_RE.search(source_full)
            if matched:
                year = int(matched.group(1))

        # ---- 多对多：知识点 / 来源试卷 ----
        knowledge = self._extract_knowledge(item)
        sources = self._extract_sources(item)

        # ---- 公式图 / 插图 ----
        formulas, images = self._extract_media(content_node)

        # ---- 角标 ----
        tags = [t for t in (s.strip() for s in item.css("span.tag::text").getall()) if t]

        return ZujuanQuestion(
            question_id=question_id,
            bank_id=_blank_to_none(item.attrib.get("bankid")),
            stem_html=stem_html or None,
            stem_status="html_saved" if stem_html else "none",
            stem_hash=md5_hex(stem_html),
            card_html=item.get(),
            list_url=list_url or None,
            page=page,
            qtype=qtype,
            qtype_code=_blank_to_none(attrs.get("qyid")),
            qtype_full=qtype_full,
            qtype_sub=split_qtype(qtype_full or ""),
            difficulty=_blank_to_none(attrs.get("qdname")),
            difficulty_code=_blank_to_none(attrs.get("qdid")),
            difficulty_band=difficulty_band(score_rate),
            score_rate=score_rate,
            source=source_full,
            title_abbr=title_abbr,
            category_id=_blank_to_none(attrs.get("categoryid")),
            category_name=_blank_to_none(attrs.get("categoryname")),
            school_year=abbr["school_year"],
            year=year,
            grade_level=abbr["grade_level"],
            term=abbr["term"],
            province=abbr["province"],
            province_code=abbr["province_code"],
            city=abbr["city"],
            source_type=abbr["source_type"],
            paper_id=sources[0].paper_id if sources else None,
            used_count=self._extract_used_count(item),
            # 角标是"有没有"，没有就是明确的 0，不是留空
            is_famous_school=1 if any("名校" in t for t in tags) else 0,
            is_real_exam=1 if any("真题" in t for t in tags) else 0,
            updated_hint=_blank_to_none(item.css(".info-msgs span.no-bound::text").get()),
            detail_url=_blank_to_none(item.css('a[data-btn-type="quesDetail"]::attr(href)').get()),
            sub_question_count=_blank_to_none(attrs.get("childnum")),
            knowledge_id=knowledge[0].id if knowledge else None,
            knowledge_tags=json.dumps([k.name for k in knowledge], ensure_ascii=False) if knowledge else None,
            knowledge=knowledge,
            sources=sources,
            formulas=formulas,
            images=images,
            tags=tags,
        )

    @staticmethod
    def _extract_knowledge(item: Selector) -> List[ZujuanKnowledge]:
        """
        知识点标签，可能 0 到 10 个不等。

        ★这里故意不去重：卡片末尾常挂着"能力标签"（href 形如
        /czsx/zsd5249/tre5-15091），正则抠出来的 id 会和前面某个知识点撞车，
        但它的名称不同（如"问题解决能力"）。原始数组要如实保留这一条 ——
        它进 JSONL 和 knowledge_tags；去重是写 question_knowledge 关联表时才做的，
        因为那张表的主键是 (question_id, knowledge_id)。
        """
        result: List[ZujuanKnowledge] = []
        for link in item.css("div.knowledge-list a"):
            matched = KNOWLEDGE_ID_RE.search(link.attrib.get("href", ""))
            if not matched:
                continue
            name = (link.attrib.get("title") or "").strip() or _clean_text(link.get())
            result.append(ZujuanKnowledge(id=matched.group(1), name=name))
        return result

    @staticmethod
    def _extract_sources(item: Selector) -> List[ZujuanSource]:
        """
        来源试卷，一题可能被多套试卷收录（卡片文案写"N 卷引用"）。

        只取展开区 div.more-src-links 里的链接：顶部摘要那条也包含在这个区块的
        集合里，单独再收一次只会打乱顺序。按 paper_id 去重。
        """
        result: List[ZujuanSource] = []
        seen = set()
        for link in item.css("div.more-src-links a"):
            href = link.attrib.get("href", "")
            matched = PAPER_HREF_RE.search(href)
            if not matched or matched.group(2) in seen:
                continue
            seen.add(matched.group(2))
            title = (link.attrib.get("title") or "").strip() or _clean_text(link.get())
            result.append(
                ZujuanSource(
                    paper_id=matched.group(2),
                    bank_id=matched.group(1),
                    title=title,
                    url=href,
                )
            )
        return result

    @staticmethod
    def _extract_media(content_node: Selector) -> Tuple[List[ZujuanFormula], List[ZujuanImage]]:
        """
        题干里的 <img> 拆成公式图和插图。

        两者属性完全一样，唯一能区分的是 URL 路径里有没有 /Upload/formula/。
        只做分类记录，不下载、不 OCR。
        """
        formulas: List[ZujuanFormula] = []
        images: List[ZujuanImage] = []
        if not content_node:
            return formulas, images

        for img in content_node.css("img"):
            url = (img.attrib.get("src") or "").strip()
            if not url:
                continue
            if FORMULA_URL_MARK in url:
                latex, latex_from = None, None
                # 试着从属性里读 LaTeX 源码。实测绝大多数读不到，
                # 留着这条路是万一站点哪天开始给就白捡，读不到就留空、不做 OCR
                for attr in ("data-latex", "alt", "title"):
                    value = (img.attrib.get(attr) or "").strip()
                    if value:
                        latex, latex_from = value, attr
                        break
                formulas.append(
                    ZujuanFormula(url=url, img_key=image_key(url), latex=latex, latex_from=latex_from)
                )
            else:
                images.append(ZujuanImage(url=url))
        return formulas, images

    @staticmethod
    def _extract_used_count(item: Selector) -> Optional[int]:
        """取 '9次组卷' 里的数字"""
        candidates = item.css(".info-msgs span::text").getall() + item.css(
            ".info-msgs span::attr(title)"
        ).getall()
        for text in candidates:
            matched = USED_COUNT_RE.search((text or "").strip())
            if matched:
                return int(matched.group(1))
        return None
