# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/model/m_kuaishou.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#



# -*- coding: utf-8 -*-

from pydantic import BaseModel, Field


class VideoUrlInfo(BaseModel):
    """Kuaishou video URL information"""
    video_id: str = Field(title="video id (photo id)")
    url_type: str = Field(default="normal", title="url type: normal")


class CreatorUrlInfo(BaseModel):
    """Kuaishou creator URL information"""
    user_id: str = Field(title="user id (creator id)")
