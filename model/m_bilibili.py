# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/model/m_bilibili.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1



# -*- coding: utf-8 -*-

from pydantic import BaseModel, Field


class VideoUrlInfo(BaseModel):
    """Bilibili video URL information"""
    video_id: str = Field(title="video id (BV id)")
    video_type: str = Field(default="video", title="video type")


class CreatorUrlInfo(BaseModel):
    """Bilibili creator URL information"""
    creator_id: str = Field(title="creator id (UID)")
