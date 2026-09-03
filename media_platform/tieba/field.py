# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/tieba/field.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#



from enum import Enum


class SearchSortType(Enum):
    """search sort type"""
    # Sort by time in descending order
    TIME_DESC = "1"
    # Sort by time in ascending order
    TIME_ASC = "0"
    # Sort by relevance
    RELEVANCE_ORDER = "2"


class SearchNoteType(Enum):
    # Only view main posts
    MAIN_THREAD = "1"
    # Mixed mode (posts + replies)
    FIXED_THREAD = "0"
