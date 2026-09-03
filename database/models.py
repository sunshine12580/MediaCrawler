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

from sqlalchemy import create_engine, Column, Integer, Text, String, BigInteger
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

class ZujuanQuestion(Base):
    __tablename__ = 'zujuan_question'
    id = Column(Integer, primary_key=True, comment='主键ID')
    question_id = Column(String(64), index=True, comment='题目ID')
    bank_id = Column(String(32), comment='题库ID')
    question_type = Column(String(64), comment='题型')
    difficulty_name = Column(String(64), comment='难度名称')
    difficulty_value = Column(String(32), comment='难度系数')
    category_id = Column(String(64), index=True, comment='知识点ID')
    category_name = Column(Text, comment='知识点名称')
    knowledge_points = Column(Text, comment='全部知识点')
    title = Column(Text, comment='来源标题')
    content_html = Column(Text, comment='题干HTML')
    content_text = Column(Text, comment='题干纯文本')
    option_list = Column(Text, comment='选项列表JSON')
    image_list = Column(Text, comment='公式/插图URL')
    answer = Column(Text, comment='答案(未登录为空)')
    analysis = Column(Text, comment='解析(未登录为空)')
    source_name = Column(Text, comment='题目出处')
    source_url = Column(Text, comment='出处试卷链接')
    used_count = Column(String(64), comment='组卷次数')
    update_label = Column(String(64), comment='更新时间标签')
    detail_url = Column(Text, comment='详情页链接')
    list_url = Column(Text, comment='来源列表页URL')
    page = Column(Integer, comment='所在列表页页码')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
