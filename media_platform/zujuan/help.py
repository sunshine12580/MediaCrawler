# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zujuan/help.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

import html as html_lib
import json
import re
from enum import Enum
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from parsel import Selector

from model.m_zujuan import ZujuanQuestion
from tools import utils

ZUJUAN_HOST = "https://zujuan.xkw.com"

# 列表页里出现题目卡片，说明确实拿到了目标数据（正向白名单，优先级最高）
_CONTENT_MARKERS = ("tk-quest-item",)

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


def build_page_url(list_url: str, page: int, page_url_template: Optional[str] = None) -> str:
    """
    拼接列表页翻页 URL。

    组卷网的翻页形如 /gzsx/zsd28745/o2 -> /gzsx/zsd28745/o2p2/，
    优先使用页面分页器里自带的 data-href 作为模板，拿不到时按规则拼。
    """
    if page <= 1:
        return list_url

    if page_url_template:
        return page_url_template.replace("{page}", str(page))

    parsed = urlparse(list_url)
    path = re.sub(r"p\d+$", "", parsed.path.rstrip("/")).rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}p{page}/"


class ZuJuanExtractor:
    """组卷网页面解析器：列表页 HTML -> 题目结构化数据"""

    def extract_page_url_template(self, page_html: str) -> Optional[str]:
        """
        从分页器里取一个真实的翻页链接作为模板，把页码替换成 {page}
        例：/gzsx/zsd28745/o2p2/ -> https://zujuan.xkw.com/gzsx/zsd28745/o2p{page}/
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
        """从分页器推断总页数，拿不到时返回 1"""
        selector = Selector(page_html)
        last_id = selector.css("a#lastpage::attr(lastid)").get()
        if last_id and last_id.isdigit():
            return int(last_id)

        pager = selector.css("div.tk-pager")
        if pager:
            total = pager.attrib.get("data-sum")
            size = pager.attrib.get("data-size")
            if total and size and total.isdigit() and size.isdigit() and int(size) > 0:
                return max(1, -(-int(total) // int(size)))
        return 1

    def extract_total_question_count(self, page_html: str) -> int:
        """列表页声明的题目总数，拿不到时返回 0"""
        pager = Selector(page_html).css("div.tk-pager")
        if pager:
            total = pager.attrib.get("data-sum")
            if total and total.isdigit():
                return int(total)
        return 0

    def extract_questions(self, page_html: str, list_url: str = "", page: int = 1) -> List[ZujuanQuestion]:
        """解析列表页里的全部题目"""
        selector = Selector(page_html)
        questions: List[ZujuanQuestion] = []
        for item in selector.css("div.tk-quest-item"):
            question = self._extract_one_question(item, list_url=list_url, page=page)
            if question and question.question_id:
                questions.append(question)
        return questions

    def _extract_one_question(self, item: Selector, list_url: str, page: int) -> Optional[ZujuanQuestion]:
        question_id = (item.attrib.get("questionid") or "").strip()
        if not question_id:
            return None

        # "加入试题篮"按钮上挂着结构化的题型/难度/知识点属性，比页面文案更稳
        btn = item.css('a[data-btn-type="quesAdd"]')
        btn_attrs: Dict[str, str] = btn.attrib if btn else {}

        info_texts = [
            text.strip()
            for text in item.css(".left-msg .addi-info .info-cnt::text").getall()
            if text.strip()
        ]
        question_type = btn_attrs.get("qyname") or (info_texts[0] if info_texts else "")
        difficulty_name = btn_attrs.get("qdname", "")
        difficulty_value = btn_attrs.get("qdvalue", "")
        if not difficulty_name and len(info_texts) > 1:
            difficulty_name, difficulty_value = self._split_difficulty(info_texts[1])

        content_node = item.css("div.exam-item__cnt")
        content_html = content_node.get() or "" if content_node else ""
        content_text = self._clean_text(content_html)

        knowledge_points = [
            text.strip() for text in item.css(".knowledge-item::text").getall() if text.strip()
        ]

        detail_href = item.css('a[data-btn-type="quesDetail"]::attr(href)').get() or ""
        src_node = item.css("a.ques-src")
        source_name = self._clean_text(src_node.get()) if src_node else ""
        source_href = src_node.attrib.get("href", "") if src_node else ""

        answer_html = item.css(".exam-item__opt .item.answer").get() or ""
        analysis_html = item.css(".exam-item__opt .item.explain").get() or ""

        return ZujuanQuestion(
            question_id=question_id,
            bank_id=(item.attrib.get("bankid") or "").strip(),
            question_type=question_type,
            difficulty_name=difficulty_name,
            difficulty_value=difficulty_value,
            category_id=btn_attrs.get("categoryid", ""),
            category_name=btn_attrs.get("categoryname", ""),
            knowledge_points=",".join(knowledge_points),
            title=btn_attrs.get("questitle", ""),
            content_html=content_html,
            content_text=content_text,
            option_list=self._extract_options(content_node),
            image_list=",".join(item.css("div.exam-item__cnt img::attr(src)").getall()),
            answer=self._clean_text(answer_html),
            analysis=self._clean_text(analysis_html),
            source_name=source_name,
            source_url=urljoin(ZUJUAN_HOST, source_href) if source_href else "",
            used_count=self._extract_used_count(item),
            update_label=(item.css(".info-msgs span.no-bound::text").get() or "").strip(),
            detail_url=urljoin(ZUJUAN_HOST, detail_href) if detail_href else "",
            list_url=list_url,
            page=page,
        )

    @staticmethod
    def _split_difficulty(text: str) -> tuple:
        """把 '容易 (0.95)' / '容易(0.85)' 拆成 ('容易', '0.95')"""
        match = re.match(r"^(.*?)\s*[（(]\s*([\d.]+)\s*[)）]\s*$", text)
        if match:
            return match.group(1).strip(), match.group(2)
        return text, ""

    @staticmethod
    def _clean_text(raw_html: str) -> str:
        """去标签 + 还原实体 + 压缩空白"""
        if not raw_html:
            return ""
        text = utils.extract_text_from_html(raw_html)
        text = html_lib.unescape(text)
        return re.sub(r"[ \t　]*\n[\s\n]*", "\n", re.sub(r"[ \t ]+", " ", text)).strip()

    def _extract_options(self, content_node: Selector) -> str:
        """
        解析选项表格，返回 JSON 字符串。
        选项常常是公式图片，所以文本和图片都保留。
        """
        if not content_node:
            return ""
        options: List[Dict[str, str]] = []
        for cell in content_node.css('table[name="optionsTable"] td'):
            cell_html = cell.get() or ""
            text = self._clean_text(cell_html)
            images = cell.css("img::attr(src)").getall()
            if not text and not images:
                continue
            label = ""
            match = re.match(r"^\s*([A-Z])\s*[．.、]", text)
            if match:
                label = match.group(1)
                text = text[match.end():].strip()
            options.append({"label": label, "text": text, "image_list": ",".join(images)})
        if not options:
            return ""
        return json.dumps(options, ensure_ascii=False)

    @staticmethod
    def _extract_used_count(item: Selector) -> str:
        """取 '9次组卷' 这类组卷次数文案"""
        for text in item.css(".info-msgs span::text").getall():
            text = text.strip()
            if re.match(r"^\d+次组卷$", text):
                return text
        for title in item.css(".info-msgs span::attr(title)").getall():
            title = title.strip()
            if re.match(r"^\d+次组卷$", title):
                return title
        return ""
