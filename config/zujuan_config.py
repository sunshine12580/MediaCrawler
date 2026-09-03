# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/zujuan_config.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

# 组卷网(学科网)平台配置

# 题库列表页 URL 列表，--type search 时按顺序抓取并自动翻页
# URL 形如 https://zujuan.xkw.com/<学科代号>/zsd<知识点ID>/o2
# 也可以直接用 --specified_id 从命令行传入，多个用英文逗号分隔
ZUJUAN_SPECIFIED_URL_LIST = [
    "https://zujuan.xkw.com/gzsx/zsd28745/o2",
    # ........................
]

# 单个列表页 URL 最多翻多少页，0 表示不限制（实际仍受 CRAWLER_MAX_NOTES_COUNT 约束）
ZUJUAN_MAX_PAGE_PER_URL = 0

# 是否抓取题干中的公式/插图 URL（写入 image_list 字段）
ZUJUAN_ENABLE_GET_IMAGES = True

# 触发阿里云 WAF 人机验证（滑块/点选）时，是否暂停并等待人工在浏览器里完成验证。
# 设为 False 则直接报错退出。注意：无头模式下人工无法操作，需要 CDP_HEADLESS/HEADLESS = False
ZUJUAN_ENABLE_HUMAN_SOLVE = True

# 等待人工完成验证的最长秒数
ZUJUAN_HUMAN_SOLVE_TIMEOUT = 180
