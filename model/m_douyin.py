# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/model/m_douyin.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#



# -*- coding: utf-8 -*-

from pydantic import BaseModel, Field


class VideoUrlInfo(BaseModel):
    """Douyin video URL information"""
    aweme_id: str = Field(title="aweme id (video id)")
    url_type: str = Field(default="normal", title="url type: normal, short, modal")


class CreatorUrlInfo(BaseModel):
    """Douyin creator URL information"""
    sec_user_id: str = Field(title="sec_user_id (creator id)")
