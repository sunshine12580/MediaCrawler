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
 "zsd5431"
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
ZUJUAN_PAGE_SLEEP_RANGE = (2.0, 4.0)

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
#   api     = 每一片的**首页**照旧用浏览器打开（过挑战、拿 Cookie 和防伪令牌、
#             读"共计 N 道试题"），之后的页直接 POST 站点自己的列表接口
#             /zujuan-api/question/list —— 不渲染，每页只有 9 KB 左右
# ★ 如果你遇到"人过完滑块后每翻一页又弹一次"，先把这里改成 browser。
#   httpx 的 TLS 指纹和 Chrome 不同，这一层换 UA 也补不平
ZUJUAN_FETCH_MODE = "browser"

# ===== api 模式的参数（ZUJUAN_FETCH_MODE = "api" 时才生效）=====
#
# 接口页码从几开始数。**已证实是 1 基**（2026-09 实测）：线上抓到的那次
# curPage=67 而 Referer 是 o2p68，是因为人当时停在第 68 页、点的是"67"这个页码
# —— curPage 是**要去的那一页**，Referer 只是从哪儿来的。所以别再被这条记录误导。
# 保留这个开关是为了站点改口时不用改代码；填 0 之外的值会在启动时报错。
ZUJUAN_API_PAGE_BASE = 1

# 每片第一次用接口之前，先拿浏览器已经取到的那一页做一次对齐校验。
# ★ 强烈建议保持 True。页码基数已经证实是 1 基了，但**筛选参数映射仍然没有验证过**
#   —— quesType/quesDiff/quesYear 对应哪个码全是照 URL 段码推的。推错了不会报错，
#   只会让筛选条件被忽略，把整个知识点的题当成某个分片入库（现象是接口返回的
#   total 等于知识点总数）。这才是现在这道校验真正在守的东西。
#   代价只有每片一次额外请求（一片动辄几百页，摊下来不到 1%）
ZUJUAN_API_VERIFY_FIRST_PAGE = True

# 接口的每页条数。0 = 不发这个参数，用站点默认的 10 条。
#
# ★ 实测（2026-09）：传 pageSize=50 **站点直接忽略**，照样返回 10 条。所以这个
#   开关目前没有实际用途，别再花时间试了。
# ★ 留着它是为了守住另一件事：只允许 0 或 10，填别的会在启动时直接报错。
#   covered_pages 里已经有几十万条按"10 条一页"记下来的页码，页大小一变这些进度
#   全部失去意义（50 条一页的第 5 页和 10 条一页的第 5 页不是同一批题），断点续采
#   会静默跳页或重复；翻页硬顶 999 页 = 9990 道也是跟着页大小走的。
#   哪天真找到了能改页大小的参数，那是一次独立的数据迁移，不是改这里一个数
ZUJUAN_API_PAGE_SIZE = 0

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
