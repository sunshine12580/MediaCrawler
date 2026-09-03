# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_zujuan_extractor.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

"""
组卷网解析器单测：用一段裁剪自真实页面的 HTML 校验字段提取与翻页 URL 拼接
"""
import json

from media_platform.zujuan.help import (
    PageStatus,
    ZuJuanExtractor,
    build_page_url,
    is_challenge_page,
    page_status,
)

LIST_HTML = """
<div class=" tk-quest-item  quesroot  " questionindex="0" questionid="35238538" bankid="11">
  <div class="ques-additional">
    <div class="top-msg">
      <span class="addi-msg">
        <a href="/11p3437781.html" title="原始出处" target="_blank" class="addi-msg ques-src">26-27高一上·全国·课后作业</a>
      </span>
    </div>
    <div class="msg-box">
      <div class="left-msg">
        <span class="addi-info"><span class="info-cnt">单选题</span></span>
        <span class="addi-info"><span class="info-cnt">容易 (0.95)</span></span>
        <div class="knowledge-list">
          <a href="/gzsx/zsd28745/" class="knowledge-item">用不等式表示不等关系</a>
          <a href="/gzsx/zsd28745/tre5-15096" class="knowledge-item">逻辑推理能力</a>
        </div>
      </div>
    </div>
  </div>
  <div class="wrapper quesdiv" id="quesdiv35238538">
    <div class="exam-item__cnt ">
      1 . 完成一项装修工程，请木工需付工资每人50元，则工人数需满足的关系式是（&nbsp;）
      <img src="https://staticzujuan.xkw.com/quesimg/a.png">
      <table name="optionsTable"><tbody>
        <tr><td>A．<img src="https://staticzujuan.xkw.com/quesimg/opt_a.png"></td></tr>
        <tr><td>B．5x+4y&lt;200</td></tr>
      </tbody></table>
    </div>
    <div hidden="" class="exam-item__opt"><div class="item answer"></div></div>
  </div>
  <div class="exam-item__info clearfix">
    <div class="info-msgs">
      <span class="no-bound" title="今日">今日</span>
      <span title="9次组卷">9次组卷</span>
    </div>
    <div class="ctrl-box">
      <a data-btn-type="quesDetail" class=" detail ctrl-btn" target="_blank" href="/11q35238538.html">详情</a>
      <a data-btn-type="quesAdd" class="addques add-exam-btn" quesid="35238538" questitle="第二章 等式性质与不等式性质"
         categoryid="28745" categoryname="用不等式表示不等关系" qyid="2701" qyname="单选题"
         qdid="1" qdname="容易" qdvalue="0.95">加入试题篮</a>
    </div>
  </div>
</div>
<div class="tk-pager" data-page-type="1" data-sum="284" data-size="10">
  <a data-type="switchPage" data-num="2" data-href="/gzsx/zsd28745/o2p2/">2</a>
  <a id="lastpage" data-type="lastPage" lastid="29" class="pager-item to-last">末页</a>
</div>
"""


def test_extract_questions_basic_fields():
    questions = ZuJuanExtractor().extract_questions(
        LIST_HTML, list_url="https://zujuan.xkw.com/gzsx/zsd28745/o2", page=1
    )
    assert len(questions) == 1
    q = questions[0]
    assert q.question_id == "35238538"
    assert q.bank_id == "11"
    assert q.question_type == "单选题"
    assert q.difficulty_name == "容易"
    assert q.difficulty_value == "0.95"
    assert q.category_id == "28745"
    assert q.category_name == "用不等式表示不等关系"
    assert q.knowledge_points == "用不等式表示不等关系,逻辑推理能力"
    assert "完成一项装修工程" in q.content_text
    assert "<img" in q.content_html
    assert q.source_name == "26-27高一上·全国·课后作业"
    assert q.source_url == "https://zujuan.xkw.com/11p3437781.html"
    assert q.detail_url == "https://zujuan.xkw.com/11q35238538.html"
    assert q.used_count == "9次组卷"
    assert q.update_label == "今日"
    assert q.page == 1
    assert q.list_url == "https://zujuan.xkw.com/gzsx/zsd28745/o2"


def test_extract_options_and_images():
    q = ZuJuanExtractor().extract_questions(LIST_HTML)[0]
    options = json.loads(q.option_list)
    assert [opt["label"] for opt in options] == ["A", "B"]
    assert options[0]["image_list"] == "https://staticzujuan.xkw.com/quesimg/opt_a.png"
    # 文本选项里的 HTML 实体要还原
    assert options[1]["text"] == "5x+4y<200"
    assert "https://staticzujuan.xkw.com/quesimg/a.png" in q.image_list


def test_answer_empty_when_not_logged_in():
    q = ZuJuanExtractor().extract_questions(LIST_HTML)[0]
    assert q.answer == ""
    assert q.analysis == ""


def test_extract_pager_info():
    extractor = ZuJuanExtractor()
    assert extractor.extract_total_page(LIST_HTML) == 29
    assert extractor.extract_total_question_count(LIST_HTML) == 284
    assert (
        extractor.extract_page_url_template(LIST_HTML)
        == "https://zujuan.xkw.com/gzsx/zsd28745/o2p{page}/"
    )


def test_build_page_url():
    base = "https://zujuan.xkw.com/gzsx/zsd28745/o2"
    assert build_page_url(base, 1) == base
    assert build_page_url(base, 3) == "https://zujuan.xkw.com/gzsx/zsd28745/o2p3/"
    # 已经带页码的 URL 要先去掉旧页码
    assert build_page_url("https://zujuan.xkw.com/gzsx/zsd28745/o2p3/", 5) == (
        "https://zujuan.xkw.com/gzsx/zsd28745/o2p5/"
    )
    # 分页器给了模板时优先用模板
    template = "https://zujuan.xkw.com/gzsx/zsd28745/o2p{page}/"
    assert build_page_url(base, 7, template) == "https://zujuan.xkw.com/gzsx/zsd28745/o2p7/"


def test_is_challenge_page():
    assert is_challenge_page('<html><body onload="check()"><input name="parm_0"></body></html>')
    assert is_challenge_page("") is True
    assert not is_challenge_page(LIST_HTML)


CHALLENGE_HTML = (
    '<html><head><script>var x = window["parm_0"];</script></head>'
    '<body onload="check()"><input name="parm_1"></body></html>'
)

CAPTCHA_HTML = (
    "<html><body><div id=\"nc-container\"></div>"
    '<script src="//g.alicdn.com/AWSC/AWSC/awsc.js"></script>'
    "<p>请完成安全验证</p></body></html>"
)


def test_page_status_ok_wins_over_markers():
    # 只要页面上有题目卡片，就是拿到了目标数据 —— 正向白名单优先级最高
    assert page_status(LIST_HTML) is PageStatus.OK
    assert page_status(LIST_HTML + CHALLENGE_HTML) is PageStatus.OK


def test_page_status_js_challenge():
    assert page_status(CHALLENGE_HTML) is PageStatus.JS_CHALLENGE


def test_page_status_captcha():
    # 人机验证页同样返回 HTTP 200，必须能和 JS 挑战页区分开，否则会被当成空数据
    assert page_status(CAPTCHA_HTML) is PageStatus.CAPTCHA
    assert page_status('<html><body>滑动验证</body></html>') is PageStatus.CAPTCHA
    assert page_status('<html><body><a href="/_____tmd_____/punish?x=1">x</a></body></html>') is (
        PageStatus.CAPTCHA
    )


def test_page_status_unknown():
    assert page_status("") is PageStatus.UNKNOWN
    assert page_status("<html><body><p>没有题目也没有拦截特征</p></body></html>") is PageStatus.UNKNOWN

