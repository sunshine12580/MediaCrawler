# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/database/models.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 教学版说明：为防止爬取到的用户个人信息被用于定位真人并私信骚扰，
# 本 ORM 不再持久化任何可识别用户的字段（用户 ID、IP 归属地、头像、
# 主页链接、签名、性别等一律不落库）。原始用户 ID 在提取层经
# tools.user_hash.anonymize_user_id 转为匿名 creator_hash 后写入，
# 仅用于"同一创作者"的内容分组；昵称保留但经 mask_nickname 中间脱敏。
# 创作者个人档案表（XhsCreator/DyCreator/WeiboCreator/TiebaCreator/
# ZhihuCreator/BilibiliUpInfo/BilibiliContactInfo）已整体移除。

from sqlalchemy import create_engine, Column, Integer, Text, String, BigInteger, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class BilibiliVideo(Base):
    __tablename__ = 'bilibili_video'
    id = Column(Integer, primary_key=True, comment='主键ID')
    video_id = Column(String(64), nullable=False, index=True, unique=True, comment='视频ID')
    video_url = Column(Text, nullable=False, comment='视频URL')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    nickname = Column(Text, comment='用户昵称(已脱敏)')
    liked_count = Column(Integer, comment='点赞数')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    video_type = Column(Text, comment='视频类型')
    title = Column(Text, comment='视频标题')
    desc = Column(Text, comment='视频描述')
    create_time = Column(BigInteger, index=True, comment='创建时间戳')
    disliked_count = Column(Text, comment='点踩数')
    video_play_count = Column(Text, comment='播放数')
    video_favorite_count = Column(Text, comment='收藏数')
    video_share_count = Column(Text, comment='分享数')
    video_coin_count = Column(Text, comment='硬币数')
    video_danmaku = Column(Text, comment='弹幕数')
    video_comment = Column(Text, comment='评论数')
    video_cover_url = Column(Text, comment='视频封面URL')
    source_keyword = Column(Text, default='', comment='来源关键词')

class BilibiliVideoComment(Base):
    __tablename__ = 'bilibili_video_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    comment_id = Column(String(128), index=True, comment='评论ID')
    video_id = Column(String(64), index=True, comment='视频ID')
    content = Column(Text, comment='评论内容')
    create_time = Column(BigInteger, comment='创建时间戳')
    sub_comment_count = Column(Text, comment='子评论数')
    parent_comment_id = Column(String(255), comment='父评论ID')
    like_count = Column(Text, default='0', comment='点赞数')

class BilibiliUpDynamic(Base):
    __tablename__ = 'bilibili_up_dynamic'
    id = Column(Integer, primary_key=True, comment='主键ID')
    dynamic_id = Column(String(128), index=True, comment='动态ID')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    user_name = Column(Text, comment='用户名称(已脱敏)')
    text = Column(Text, comment='动态内容')
    type = Column(Text, comment='动态类型')
    pub_ts = Column(BigInteger, comment='发布时间戳')
    total_comments = Column(Integer, comment='总评论数')
    total_forwards = Column(Integer, comment='总转发数')
    total_liked = Column(Integer, comment='总点赞数')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')

class DouyinAweme(Base):
    __tablename__ = 'douyin_aweme'
    id = Column(Integer, primary_key=True, comment='主键ID')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    aweme_id = Column(String(255), index=True, comment='作品ID')
    aweme_type = Column(Text, comment='作品类型')
    title = Column(Text, comment='作品标题')
    desc = Column(Text, comment='作品描述')
    create_time = Column(BigInteger, index=True, comment='创建时间戳')
    liked_count = Column(Text, comment='点赞数')
    comment_count = Column(Text, comment='评论数')
    share_count = Column(Text, comment='分享数')
    collected_count = Column(Text, comment='收藏数')
    aweme_url = Column(Text, comment='作品URL')
    cover_url = Column(Text, comment='封面URL')
    video_download_url = Column(Text, comment='视频下载URL')
    music_download_url = Column(Text, comment='音乐下载URL')
    note_download_url = Column(Text, comment='笔记下载URL')
    source_keyword = Column(Text, default='', comment='来源关键词')

class DouyinAwemeComment(Base):
    __tablename__ = 'douyin_aweme_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    comment_id = Column(String(255), index=True, comment='评论ID')
    aweme_id = Column(String(255), index=True, comment='作品ID')
    content = Column(Text, comment='评论内容')
    create_time = Column(BigInteger, comment='创建时间戳')
    sub_comment_count = Column(Text, comment='子评论数')
    parent_comment_id = Column(String(255), comment='父评论ID')
    like_count = Column(Text, default='0', comment='点赞数')
    pictures = Column(Text, default='', comment='图片')

class KuaishouVideo(Base):
    __tablename__ = 'kuaishou_video'
    id = Column(Integer, primary_key=True, comment='主键ID')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    video_id = Column(String(255), index=True, comment='视频ID')
    video_type = Column(Text, comment='视频类型')
    title = Column(Text, comment='视频标题')
    desc = Column(Text, comment='视频描述')
    create_time = Column(BigInteger, index=True, comment='创建时间戳')
    liked_count = Column(Text, comment='点赞数')
    viewd_count = Column(Text, comment='观看数')
    video_url = Column(Text, comment='视频URL')
    video_cover_url = Column(Text, comment='视频封面URL')
    video_play_url = Column(Text, comment='视频播放URL')
    source_keyword = Column(Text, default='', comment='来源关键词')

class KuaishouVideoComment(Base):
    __tablename__ = 'kuaishou_video_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    comment_id = Column(String(255), index=True, comment='评论ID')
    video_id = Column(String(255), index=True, comment='视频ID')
    content = Column(Text, comment='评论内容')
    create_time = Column(BigInteger, comment='创建时间戳')
    sub_comment_count = Column(Text, comment='子评论数')

class WeiboNote(Base):
    __tablename__ = 'weibo_note'
    id = Column(Integer, primary_key=True, comment='主键ID')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    note_id = Column(String(64), index=True, comment='笔记ID')
    content = Column(Text, comment='笔记内容')
    create_time = Column(BigInteger, index=True, comment='创建时间戳')
    create_date_time = Column(String(255), index=True, comment='创建日期时间')
    liked_count = Column(Text, comment='点赞数')
    comments_count = Column(Text, comment='评论数')
    shared_count = Column(Text, comment='分享数')
    note_url = Column(Text, comment='笔记URL')
    source_keyword = Column(Text, default='', comment='来源关键词')

class WeiboNoteComment(Base):
    __tablename__ = 'weibo_note_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    comment_id = Column(String(64), index=True, comment='评论ID')
    note_id = Column(String(64), index=True, comment='笔记ID')
    content = Column(Text, comment='评论内容')
    create_time = Column(BigInteger, comment='创建时间戳')
    create_date_time = Column(String(255), index=True, comment='创建日期时间')
    comment_like_count = Column(Text, comment='评论点赞数')
    sub_comment_count = Column(Text, comment='子评论数')
    parent_comment_id = Column(String(255), comment='父评论ID')

class XhsNote(Base):
    __tablename__ = 'xhs_note'
    id = Column(Integer, primary_key=True, comment='主键ID')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    note_id = Column(String(255), index=True, comment='笔记ID')
    type = Column(Text, comment='笔记类型')
    title = Column(Text, comment='笔记标题')
    desc = Column(Text, comment='笔记描述')
    video_url = Column(Text, comment='视频URL')
    time = Column(BigInteger, index=True, comment='时间戳')
    last_update_time = Column(BigInteger, comment='最后更新时间戳')
    liked_count = Column(Text, comment='点赞数')
    collected_count = Column(Text, comment='收藏数')
    comment_count = Column(Text, comment='评论数')
    share_count = Column(Text, comment='分享数')
    image_list = Column(Text, comment='图片列表')
    tag_list = Column(Text, comment='标签列表')
    note_url = Column(Text, comment='笔记URL')
    source_keyword = Column(Text, default='', comment='来源关键词')
    xsec_token = Column(Text, comment='Xsec Token')

class XhsNoteComment(Base):
    __tablename__ = 'xhs_note_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    comment_id = Column(String(255), index=True, comment='评论ID')
    create_time = Column(BigInteger, index=True, comment='创建时间戳')
    note_id = Column(String(255), comment='笔记ID')
    content = Column(Text, comment='评论内容')
    sub_comment_count = Column(Integer, comment='子评论数')
    pictures = Column(Text, comment='图片')
    parent_comment_id = Column(String(255), comment='父评论ID')
    like_count = Column(Text, comment='点赞数')

class TiebaNote(Base):
    __tablename__ = 'tieba_note'
    id = Column(Integer, primary_key=True, comment='主键ID')
    note_id = Column(String(644), index=True, comment='笔记ID')
    title = Column(Text, comment='笔记标题')
    desc = Column(Text, comment='笔记描述')
    note_url = Column(Text, comment='笔记URL')
    publish_time = Column(String(255), index=True, comment='发布时间')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    user_nickname = Column(Text, default='', comment='用户昵称(已脱敏)')
    tieba_id = Column(String(255), default='', comment='贴吧ID')
    tieba_name = Column(Text, comment='贴吧名称')
    tieba_link = Column(Text, comment='贴吧链接')
    total_replay_num = Column(Integer, default=0, comment='总回复数')
    total_replay_page = Column(Integer, default=0, comment='总回复页数')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    source_keyword = Column(Text, default='', comment='来源关键词')

class TiebaComment(Base):
    __tablename__ = 'tieba_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    comment_id = Column(String(255), index=True, comment='评论ID')
    parent_comment_id = Column(String(255), default='', comment='父评论ID')
    content = Column(Text, comment='评论内容')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    user_nickname = Column(Text, default='', comment='用户昵称(已脱敏)')
    tieba_id = Column(String(255), default='', comment='贴吧ID')
    tieba_name = Column(Text, comment='贴吧名称')
    tieba_link = Column(Text, comment='贴吧链接')
    publish_time = Column(String(255), index=True, comment='发布时间')
    sub_comment_count = Column(Integer, default=0, comment='子评论数')
    note_id = Column(String(255), index=True, comment='笔记ID')
    note_url = Column(Text, comment='笔记URL')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')

class ZhihuContent(Base):
    __tablename__ = 'zhihu_content'
    id = Column(Integer, primary_key=True, comment='主键ID')
    content_id = Column(String(64), index=True, comment='内容ID')
    content_type = Column(Text, comment='内容类型')
    content_text = Column(Text, comment='内容文本')
    content_url = Column(Text, comment='内容URL')
    question_id = Column(String(255), comment='问题ID')
    title = Column(Text, comment='标题')
    desc = Column(Text, comment='描述')
    created_time = Column(String(32), index=True, comment='创建时间')
    updated_time = Column(Text, comment='更新时间')
    voteup_count = Column(Integer, default=0, comment='赞同数')
    comment_count = Column(Integer, default=0, comment='评论数')
    source_keyword = Column(Text, comment='来源关键词')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    user_nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')

class ZhihuComment(Base):
    __tablename__ = 'zhihu_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    comment_id = Column(String(64), index=True, comment='评论ID')
    parent_comment_id = Column(String(64), comment='父评论ID')
    content = Column(Text, comment='评论内容')
    publish_time = Column(String(32), index=True, comment='发布时间')
    sub_comment_count = Column(Integer, default=0, comment='子评论数')
    like_count = Column(Integer, default=0, comment='点赞数')
    dislike_count = Column(Integer, default=0, comment='点踩数')
    content_id = Column(String(64), index=True, comment='内容ID')
    content_type = Column(Text, comment='内容类型')
    creator_hash = Column(String(64), index=True, comment='创作者匿名哈希')
    user_nickname = Column(Text, comment='用户昵称(已脱敏)')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')

# ---------------------------------------------------------------------------
# 组卷网：映射到题库已有的三张表（questions / question_knowledge / question_sources）
#
# ★ questions 是一张多阶段共享的大表（56 列）：抓取、答案、离线渲染各写各的列。
#   这里**只声明抓取阶段负责的列** —— SQLAlchemy 永远不会碰模型里没声明的列，
#   于是"绝不能覆盖 answer_img / stem_md / render_status 等其它阶段产物"这条纪律
#   就从结构上得到保证，而不是靠写代码时记得躲开。
#
# ★ stem_text 也故意不声明：实测库里 1/2000 非空，且它的口径是离线产物
#   （公式要裸 LaTeX、插图要 [图N] 占位），抓取阶段产不出来，写了反而会让
#   离线阶段分不清"还没加工"和"已加工"。
#
# ★ 这三张表由 docs/zujuan/题干入库规范.md 的 DDL 手工建好，不走 create_all，
#   所以这里的列定义不完整不影响建表（见 main.py 里 zujuan 跳过自动建表）。
# ---------------------------------------------------------------------------


class ZujuanQuestion(Base):
    """题目主表（共享），只映射抓取阶段负责的 35 列"""

    __tablename__ = 'questions'
    question_id = Column(String(64), primary_key=True, comment='题目ID')
    grade = Column(String(8), comment='学段：middle=初中 / high=高中')
    bank_id = Column(String(16), comment='题库编号，初中数学=2')

    stem_html = Column(Text, comment='题干HTML，已剥位置号')
    stem_status = Column(String(16), comment='题干进度：none / html_saved')
    stem_hash = Column(String(32), comment='stem_html 的 md5，重复抓取判重用')

    qtype = Column(String(32), comment='题型大类')
    qtype_code = Column(String(16), comment='题型码')
    qtype_full = Column(String(32), comment='完整题型，如 解答题-计算题')
    qtype_sub = Column(String(16), comment='题型子类型')

    difficulty = Column(String(16), comment='5档难度名')
    difficulty_code = Column(String(8), comment='5档难度码')
    difficulty_band = Column(String(8), comment='3档难度，由 score_rate 重算')
    score_rate = Column(Float, comment='得分率')

    source = Column(Text, comment='来源试卷全名')
    title_abbr = Column(String(128), comment='三段式简称原串')
    category_id = Column(String(16), comment='所属章节ID')
    category_name = Column(String(64), comment='所属章节名')

    school_year = Column(String(16), comment='学年，如 2025-2026')
    year = Column(Integer, comment='年份')
    grade_level = Column(String(16), comment='年级')
    term = Column(String(16), comment='学期')
    province = Column(String(16), comment='省份')
    province_code = Column(String(8), comment='省级行政区划码')
    city = Column(String(32), comment='地级市，直辖市为空')
    source_type = Column(String(32), comment='来源类型')

    paper_id = Column(String(32), comment='主来源试卷ID')
    used_count = Column(Integer, comment='被组卷引用次数')
    is_famous_school = Column(Integer, comment='名校角标 1/0')
    is_real_exam = Column(Integer, comment='真题角标 1/0')

    list_url = Column(Text, comment='这道题是在哪个列表页抓到的')
    knowledge_id = Column(String(32), comment='主知识点ID')
    knowledge_tags = Column(Text, comment='全部知识点名称的JSON数组')

    raw_day = Column(String(10), comment='原始JSONL落在哪一天的文件')
    first_seen_at = Column(String(32), comment='第一次见到这道题的时刻，只在INSERT时写')


class ZujuanQuestionKnowledge(Base):
    """一题多知识点关联表，解析产物，先删后插"""

    __tablename__ = 'question_knowledge'
    question_id = Column(String(64), primary_key=True, comment='题目ID')
    knowledge_id = Column(String(32), primary_key=True, comment='知识点ID')
    knowledge_name = Column(String(128), comment='知识点名称')
    ord = Column(Integer, comment='卡片上的先后顺序，0 是主知识点')


class ZujuanQuestionSource(Base):
    """一题多来源试卷关联表，解析产物，先删后插"""

    __tablename__ = 'question_sources'
    question_id = Column(String(64), primary_key=True, comment='题目ID')
    paper_id = Column(String(32), primary_key=True, comment='来源试卷ID')
    paper_title = Column(Text, comment='试卷全名')
    ord = Column(Integer, comment='顺序，0 是卡片上显示的主来源')


# ---------------------------------------------------------------------------
# 知识点树与切片进度
#
# knowledge_tree 同样是共享表：树结构那一组列（node_id / title / parent_id /
# level / path / href / is_knowledge / child_count / sort_ord / updated_at）
# 归"知识点树同步"那条线，抓题这条线只写进度列。这里为了能读树结构把两组列
# 都声明了，写入侧的纪律由 store/zujuan/_progress.py 的 TREE_PROGRESS_COLUMNS
# 白名单强制保证 —— 任何一次 UPDATE 只要出现结构列就直接抛错。
# ---------------------------------------------------------------------------


class ZujuanKnowledgeTree(Base):
    """知识点树快照 + 每个知识点的采集进度"""

    __tablename__ = 'knowledge_tree'

    # ---- 第一组：树结构，只读不写 ----
    knowledge_id = Column(String(32), primary_key=True, comment='知识点ID，带 zsd 前缀')
    node_id = Column(String(32), comment='树JSON里的原始数字ID，不带前缀')
    bank_id = Column(String(16), comment='学科库编号，初中数学=2')
    title = Column(String(128), comment='知识点名称')
    parent_id = Column(String(32), comment='父节点knowledge_id')
    level = Column(Integer, comment='层级，根=0')
    path = Column(String(512), comment='从根到本节点的标题路径')
    href = Column(String(128), comment='站点链接 /czsx/zsd4700')
    is_knowledge = Column(Integer, comment='站点的isKnowledge标记')
    child_count = Column(Integer, comment='直接子节点数，0表示叶子')
    sort_ord = Column(Integer, comment='同级里的顺序')
    updated_at = Column(String(32), comment='树最后一次同步时刻')

    # ---- 第二组：采集进度，本项目负责写 ----
    is_leaf = Column(Integer, comment='是不是叶子节点，只有叶子才抓')
    scrape_status = Column(String(16), comment='none/partial/slicing/done/capped/empty')
    site_total = Column(Integer, comment='站点说这个知识点有多少道题')
    collected = Column(Integer, comment='库里这个知识点有多少道题，必须重算不能累加')
    last_page = Column(Integer, comment='上次采到第几页')
    covered_pages = Column(Text, comment='已经采过的页码区间，如 1-40,88-120')
    scraped_at = Column(String(32), comment='上次采集时刻')
    note = Column(String(255), comment='人话备注')


class ZujuanKnowledgeSlice(Base):
    """题多到翻页翻不完的知识点，按筛选条件切开之后每一片的进度"""

    __tablename__ = 'knowledge_slice'

    knowledge_id = Column(String(32), primary_key=True, comment='知识点ID，带 zsd 前缀')
    slice_key = Column(String(32), primary_key=True, comment='切片标识，如 t4d1s1')
    dim = Column(String(16), comment='按哪一维切出来的：qtype/difficulty/sub_type/year')
    slice_name = Column(String(64), comment='人话名字，如 解答题·容易·计算题')
    depth = Column(Integer, comment='维度在级联里的序号：qtype=1 difficulty=2 sub_type=3 year=4')
    scrape_status = Column(String(16), comment='none/partial/slicing/done/capped/empty')
    site_total = Column(Integer, comment='站点说这一片有多少道题')
    collected = Column(Integer, comment='库里这一片有多少道题，必须重算不能累加')
    last_page = Column(Integer, comment='这一片上次采到第几页')
    covered_pages = Column(Text, comment='这一片已经采过的页码区间')
    scraped_at = Column(String(32), comment='上次采集时刻')
    note = Column(String(255), comment='人话备注')
