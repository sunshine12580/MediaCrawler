# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/weibo_config.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#



# Weibo platform configuration

# Search type, the specific enumeration value is in media_platform/weibo/field.py
WEIBO_SEARCH_TYPE = "default"

# Specify Weibo ID list
WEIBO_SPECIFIED_ID_LIST = [
    "4982041758140155",
    # ........................
]

# Specify Weibo user ID list
WEIBO_CREATOR_ID_LIST = [
    "5756404150",
    # ........................
]

# Whether to enable the function of crawling the full text of Weibo. It is enabled by default.
# If turned on, it will increase the probability of being risk controlled, which is equivalent to a keyword search request that will traverse all posts and request the post details again.
ENABLE_WEIBO_FULL_TEXT = True
