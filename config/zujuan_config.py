# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/zujuan_config.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

# 组卷网(学科网)平台配置

# 题库列表页 URL 列表，--type search 时按顺序抓取并自动翻页
# URL 形如 https://zujuan.xkw.com/<学段学科>/zsd<知识点ID>/o2
#   czsx = 初中数学，gzsx = 高中数学 —— ★必须和下面的 ZUJUAN_GRADE 对上，
#   两个学段的 zsd 知识点 ID 不通用，混进同一张表会污染关联表
# 也可以直接用 --specified_id 从命令行传入，多个用英文逗号分隔
ZUJUAN_SPECIFIED_URL_LIST = [
    "https://zujuan.xkw.com/czsx/zsd5249/o2",
    # ........................
]

# 学段固定值，写进 questions.grade。middle=初中(czsx) / high=高中(gzsx)
ZUJUAN_GRADE = "middle"

# 列表页 URL 里的学段前缀，必须和 ZUJUAN_GRADE 对上：middle -> czsx，high -> gzsx
ZUJUAN_URL_PREFIX = "czsx"

# ===== 抓取模式 =====

# knowledge = 按 knowledge_tree 里的叶子知识点遍历（断点续采、超量自动切片）
# url       = 只抓 ZUJUAN_SPECIFIED_URL_LIST 里写死的那几个列表页
# watch     = ★人工翻页：你在浏览器里自己翻，脚本只把你停留的每一页解析入库。
#             全程只读页面内容 —— 不 goto、不 click、不发 httpx 请求，
#             翻页和过验证完全由你操作，脚本在这个模式下是记事本不是浏览器
ZUJUAN_CRAWL_MODE = "knowledge"

# 人工翻页模式下多久扫一次浏览器标签页（秒）。调小除了多占点 CPU 没别的坏处 ——
# 它只读内存里已经渲染好的 DOM，不产生任何网络请求
ZUJUAN_WATCH_INTERVAL_SEC = 1.5

# 启动时自动打开第一个待采知识点的续采页，一个知识点采完自动跳到下一个。
# 这是 watch 模式下脚本唯一会做的导航动作（每个知识点一次，相当于替你把地址
# 粘进地址栏），翻页仍然全部由你操作。
# ★ 如果发现这几次跳转会触发人机验证，关掉它，改用 data/zujuan_survey.html
#   里的清单自己点 —— 日志里照样会打出下一个该采的地址
ZUJUAN_WATCH_AUTO_OPEN = True

# ===== 按知识点抓取（见 docs/zujuan/知识点切片抓取规范.md）=====

# 只抓这个学科库的知识点，初中数学=2。留空则不按 bank_id 过滤
ZUJUAN_BANK_ID = "2"

# 本次运行最多处理几个知识点，0 表示把待办的全部跑完。
# 待办 = knowledge_tree 里 child_count=0 且 scrape_status 属于 none/partial/slicing 的行，
# 半路停下的（partial/slicing）排在前面优先收尾
ZUJUAN_KNOWLEDGE_LIMIT = 0

# 只抓指定的几个知识点（带 zsd 前缀），填了就忽略上面的状态筛选，
# 方便重跑单个知识点。也可以用 --specified_id 从命令行传入
ZUJUAN_KNOWLEDGE_ID_LIST = [
"zsd5514","zsd5544","zsd4839","zsd5980","zsd5921","zsd5592","zsd5516","zsd5986","zsd5922","zsd4834","zsd5914","zsd4837","zsd5518","zsd5462","zsd5407","zsd5517","zsd5561","zsd5976","zsd5047","zsd5614","zsd5719","zsd5918","zsd5045","zsd5551","zsd223840","zsd5983","zsd5708","zsd5572","zsd5955","zsd5405","zsd5049","zsd4762","zsd5043","zsd4956","zsd5341","zsd5989","zsd5718","zsd5860","zsd5385","zsd5709","zsd5945","zsd5042","zsd5897","zsd5671","zsd5896","zsd5917","zsd5319","zsd4833","zsd5033","zsd4925","zsd4785","zsd4928","zsd212324","zsd5522","zsd4778","zsd4844","zsd5404","zsd5421","zsd5996","zsd212315","zsd5416","zsd4955","zsd4931","zsd5618","zsd5449","zsd5469","zsd4969","zsd5947","zsd5508","zsd5115","zsd182536","zsd5603","zsd5940","zsd182532","zsd5919","zsd5623","zsd5488","zsd212337","zsd5666","zsd5114","zsd4768","zsd5849","zsd5539","zsd5596","zsd4732","zsd4966","zsd212305","zsd6031","zsd5245","zsd5492","zsd5548","zsd5730","zsd214890","zsd5594","zsd5466","zsd5559","zsd4933","zsd4866","zsd4756","zsd5944","zsd4967","zsd4953","zsd5682","zsd5675","zsd188417"
]

# ===== 浅采（广度优先扫一遍）=====
#
# 每个知识点最多翻几页，0 = 不限（正常的深采）。设成正数就进入"浅采"模式：
# 每个知识点翻前 N 页就换下一个，用来给全部知识点铺一层底，
# 顺带把每个知识点的 site_total 摸出来（第 1 页就能读到"共计 N 道试题"）。
#
# ★ 浅采模式下同时会关掉超量切片 —— 题量超过翻页硬顶的知识点不再当场炸出一堆
#   分片去挨个采，而是照样翻 N 页就走，状态留 partial，等以后深采时再切。
ZUJUAN_MAX_PAGES_PER_KNOWLEDGE = 0

# 只挑 scrape_status='none'（从来没跑过）的叶子知识点。
# ★ 浅采跑完的知识点状态会变成 partial，所以打开这个开关重跑会自动跳过已经
#   浅采过的，中断了直接再跑一遍即可，不用手工记进度
ZUJUAN_ONLY_UNCRAWLED = False

# 按 knowledge_tree.path 里的关键字排除整个分支，如 ["五四制小学衔接", "数学竞赛"]
ZUJUAN_EXCLUDE_PATHS = []

# 忽略 knowledge_tree/knowledge_slice 里已有的状态和页码，一律从第 1 页重跑。
# 配合 ZUJUAN_KNOWLEDGE_ID_LIST 重采某个已经标成 done 的知识点时打开；
# 单题层面还有 stem_hash 判重兜底，重跑不会把已有题干覆盖掉
ZUJUAN_FORCE_RECRAWL = False

# 本次运行最多入库多少道题，0 表示不限。
# ★ 按知识点抓取不看 CRAWLER_MAX_NOTES_COUNT（那个默认才 50，会让一个知识点
#   刚翻 5 页就停），预算一律走这里
ZUJUAN_MAX_QUESTIONS_PER_RUN = 0

# 翻完一页之后的等待秒数区间，每页在区间里随机取 —— 固定间隔本身就是机器特征
ZUJUAN_PAGE_SLEEP_RANGE = (3.0, 8.0)

# 换下一个知识点之前的等待秒数区间，比翻页间隔长一些
ZUJUAN_KNOWLEDGE_SLEEP_RANGE = (24.0, 48.0)

# 单个列表页 URL 最多翻多少页，0 表示不限制（实际仍受 CRAWLER_MAX_NOTES_COUNT 约束）
ZUJUAN_MAX_PAGE_PER_URL = 0

# ===== 入库策略（见 docs/zujuan/题干入库规范.md 第 5 节）=====

# 库里已有这道题、且 stem_hash 非空时直接跳过，连关联表都不动。
# 不拿新抓到的内容和库里比对 —— 剥过位置号后内容本来就该是稳定的，
# 比对只会因为 list_url 之类的上下文差异产生大量无意义的重写
ZUJUAN_SKIP_EXISTING = True

# 组卷网写的是外部已建好的题库表，默认不跑 MediaCrawler 的自动建表。
# ★开成 True 会把 Base.metadata 里另外 15 张平台表一并建进你的库
ZUJUAN_AUTO_CREATE_TABLES = False

# ===== 原始 JSONL 快照（与数据库双写）=====

# 每道题都留一份含整张卡片原文的 JSONL，解析规则改了可以离线重跑，不用重新抓
ZUJUAN_ENABLE_RAW_JSONL = True

# 快照目录，文件名形如 2026-08-23-n1.jsonl；questions.raw_day 记的就是这里的日期
ZUJUAN_RAW_DIR = "data/raw"

# 单个分片写满多少行开下一个（n1 -> n2 -> ...）
ZUJUAN_RAW_SHARD_SIZE = 20000

# ===== 反爬 =====

# 取页面的方式：
#   hybrid  = 先用 httpx（快），被拦才退回浏览器
#   browser = 全程走浏览器（慢很多，但和真人浏览是同一条路径）
# ★ 如果你遇到"人过完滑块后每翻一页又弹一次"，先把这里改成 browser。
#   httpx 的 TLS 指纹和 Chrome 不同，这一层换 UA 也补不平
ZUJUAN_FETCH_MODE = "browser"

# 浏览器翻页时优先"点分页器"而不是直接 goto 深链接。
# 直接 goto /o2p387/ 等于往地址栏连续粘贴几百个深链接：没有导航链、
# 不触发站点自己的翻页 JS。点分页器才是站点期望的那条路径。
# 找不到分页器链接、或点完确认不了页码时会自动退回 goto（日志里会说明原因）
ZUJUAN_HUMAN_PAGING = True


# 触发阿里云 WAF 人机验证（滑块/点选）时，是否暂停并等待人工在浏览器里完成验证。
# 设为 False 则直接报错退出。注意：无头模式下人工无法操作，需要 CDP_HEADLESS/HEADLESS = False
ZUJUAN_ENABLE_HUMAN_SOLVE = True

# 等待人工完成验证的最长秒数
ZUJUAN_HUMAN_SOLVE_TIMEOUT = 1800
