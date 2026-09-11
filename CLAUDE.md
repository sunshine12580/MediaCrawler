# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

MediaCrawler 是一个异步的多平台自媒体爬虫（小红书 `xhs`、抖音 `dy`、快手 `ks`、B 站 `bili`、微博 `wb`、百度贴吧 `tieba`、知乎 `zhihu`，以及题库站组卷网 `zujuan`）。它用 Playwright 驱动真实浏览器拿到登录态上下文，再用 `httpx` 直接调用各平台 Web API；签名参数取自浏览器上下文中执行的 JS，而不是重新实现加密算法。

Python >= 3.11，用 `uv` 管理依赖。运行期还需要 Node.js >= 16：抖音和知乎的签名要通过 `pyexecjs` 执行 `libs/*.js`。

## 常用命令

```shell
uv sync                                   # 安装依赖（锁定 Python 版本 + lockfile）
uv run playwright install                 # 仅在 ENABLE_CDP_MODE = False 时需要

uv run main.py --platform xhs --lt qrcode --type search
uv run main.py --help                     # 完整参数列表（Typer，按面板分组）
uv run main.py --init_db sqlite           # 建表（sqlite | mysql | postgres）

uv run pytest tests/                      # 单元测试（基于 mock，不走网络）
uv run pytest tests/test_no_user_info.py -v
uv run pytest tests/test_xhs_core_access_error.py::test_name

uv run pre-commit run --all-files         # 文件头检查 + 空白/YAML 钩子
```

注意有两个测试目录：`tests/`（复数）是快速套件，带 `conftest.py` fixtures，异步用例显式标注 `@pytest.mark.asyncio`（strict 模式）；`test/`（单数）是更早期的集成测试，需要真实的 Redis / MongoDB / MySQL，只应按需单独跑，不要并入默认套件。

WebUI（FastAPI 后端 + React/Vite 前端）：

```shell
uv run uvicorn api.main:app --port 8080 --reload   # 后端
cd webui && npm install && npm run dev             # 前端 :5173，/api 代理到 :8080
cd webui && npm run build                          # 产物输出到 api/webui/，之后由 :8080 直接托管
npm run docs:dev                                   # VitePress 文档（根目录 package.json）
```

## 架构

### 运行主流程

`main.py` → `cmd_arg.parse_cmd()` → `CrawlerFactory.create_crawler(config.PLATFORM)` → `crawler.start()`。

每个 `media_platform/<平台>/core.py` 实现的 `AbstractCrawler.start()` 结构完全一致：构建代理（可选）→ 启动浏览器（CDP 或标准 Playwright）→ 打开首页 → 构造该平台的 API client → `client.pong()` 判断登录态，未登录则执行 `login.begin()` → 按 `config.CRAWLER_TYPE` 分发到 `search()` / `get_specified_*()` / `get_creators_*()` → 逐条调用 `store.update_*()`，评论抓取在 `asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)` 下并发展开。

`tools/app_runner.run()` 包裹 `main()`，负责信号处理与 `async_cleanup()`（关闭 CDP 浏览器或浏览器上下文、落盘 Excel、生成词云、关闭数据库）。

### 配置是可变的全局状态

`config/` 是一个包而不是单个文件：`config/base_config.py` 在文件末尾星号导入了所有 `config/<平台>_config.py`，所以 `import config; config.XHS_CREATOR_ID_LIST` 才能用。`cmd_arg/arg.py` 在解析完命令行后**直接回写 `config` 模块**（`config.PLATFORM = ...`、`config.KEYWORDS = ...`）——命令行参数是通过修改模块属性生效的，而这些参数的默认值又来自 config 模块。因此在模块导入期读取的 config 值是命令行生效之前的旧值：请在函数内部读 `config.X`，不要在模块顶层读。

`--specified_id` / `--creator_id` 在 `arg.py` 里被分发到各平台专属的列表变量（`XHS_SPECIFIED_NOTE_URL_LIST`、`BILI_CREATOR_ID_LIST` 等）；新增平台必须同时补齐这两条 `if/elif` 链。

`var.py` 存放 `ContextVar`（`source_keyword_var`、`crawler_type_var` 等），把单次运行的上下文信息带到存储层，避免层层传参。

密钥与数据库连接信息来自 `.env`（参考 `.env.example`），由 `config/db_config.py` 读取。

### 各平台包的固定结构

每个 `media_platform/<平台>/` 都遵循同一套文件约定：

- `core.py` —— `AbstractCrawler` 实现（浏览器生命周期、抓取编排）
- `client.py` —— `AbstractApiClient`：请求签名、请求头、重试、翻页、评论遍历；混入 `ProxyRefreshMixin`，代理过期时可在运行中自动更换
- `login.py` —— `AbstractLogin`：`login_by_qrcode` / `login_by_mobile` / `login_by_cookies`
- `field.py`（排序/搜索参数枚举）、`help.py`（签名与解析辅助函数）、`exception.py`

例外是 `media_platform/zujuan/`：组卷网列表页无需登录，因此没有 `login.py`，`help.py` 里放的是 HTML 解析器 `ZuJuanExtractor` 而不是签名逻辑。它在 CDN 层有阿里云 WAF，直接 httpx 请求只会拿到挑战脚本，所以 `core.py` 先用浏览器打开一次首页过挑战，再把 Cookie 交给 httpx 翻页。该平台只支持 `--type search`，其下又分两种抓法，由 `ZUJUAN_CRAWL_MODE` 切换：`url` 按 `ZUJUAN_SPECIFIED_URL_LIST` 里写死的列表页抓；`knowledge`（默认）按 `knowledge_tree` 表里的叶子知识点遍历，带断点续采和超量自动切片，见下。

组卷网的存储层和其它平台完全不同，它写的是**外部已有的题库库**（`questions` / `question_knowledge` / `question_sources`），口径由 `docs/zujuan/题干解析规范.md` 和 `题干入库规范.md` 两份文档定死，必须和原采集程序逐字段一致。几条不能破的规则：

- `questions` 是多阶段共享的大表（56 列），抓取阶段只写其中 35 列，`answer_*` / `stem_md` / `render_status` / `stem_text` 等归答案抓取和离线渲染阶段。保证手段是**ORM 里根本不声明那些列** —— SQLAlchemy 碰不到没声明的列，比靠代码纪律躲开可靠。
- 写入前先查 `stem_hash`，非空就整题跳过（连关联表都不动）；`first_seen_at` 只在 INSERT 时写一次。`build_question_row()` 会丢掉所有 None 和空串但**保留 0**（`is_famous_school=0` 是"确认没有名校角标"）。
- 两张关联表先删后插，三处写入在同一个事务里；知识点要按 id 去重后重新连续编号 `ord` —— 卡片末尾的"能力标签"抠出的 id 会和前面的知识点撞车，而原始数组里那条重复项必须如实保留进 JSONL 和 `knowledge_tags`。
- 表由 `docs/zujuan/schema.sql` 手工建好，`ZUJUAN_AUTO_CREATE_TABLES = False` 关掉了 `main.py` 的自动建表 —— 否则 `Base.metadata` 里另外 15 张平台表会被建进人家的生产库。
- 每道题**双写**：先落一份含整张卡片原文的原始 JSONL（`data/raw/<日期>-n<序号>.jsonl`，满 2 万行换分片），再写数据库；`questions.raw_day` 记的就是那个日期，顺序不能反。
- 解析上几个反直觉的点：题干取 `div.exam-item__cnt` 的 **innerHTML** 并剥掉开头的位置号（那是"本页第几题"，不剥 `stem_hash` 每次都变）；`qtype_full` 只在正文第一个 `span.info-cnt` 里，按钮属性只有大类，所以**每次都要读**不是兜底；`difficulty_band` 是由 `score_rate` 重算的第三套 3 档编码，和按钮的 5 档数字会撞车；`sources` 只从 `div.more-src-links a` 收集（顶部那条摘要链接也在里面，单独再收会打乱顺序）。

`tools/zujuan_db_inspect.py` 是只读巡检脚本，对照规范检查线上表结构、字符集和数据现状。

### 组卷网人工翻页模式（`ZUJUAN_CRAWL_MODE = "watch"`）

人在浏览器里自己翻页，脚本只把他停留的每一页解析入库。**脚本在这个模式下是记事本不是浏览器**：`start()` 里提前分流，不 `new_page()`、不 `goto`、不 `click`、不建 httpx 客户端，只在轮询里读 `page.content()`。导航和过人机验证全部由人完成。

- `_scan_open_pages()` 每 `ZUJUAN_WATCH_INTERVAL_SEC` 秒扫一遍 `browser_context.pages`，只处理 URL 能被 `slicing.parse_list_url()` 认出来的列表页；别的标签页一律不碰。`page_status()` 不是 OK（验证页/挑战页）时只提示不解析。
- 用 `(url, first_question_id)` 去重，人停在同一页不动不会反复入库；多个标签页同时开着会一起处理。
- **`parse_list_url()` 认不出必须返回 `None` 而不是猜**：人工模式下地址栏是唯一的归属依据，猜错会把 A 知识点的题和进度记到 B 头上，而且不报错。这套反解和 `build_list_url()` 严格互逆，拿库里 5000 条真实 `list_url` 验过 0 差异。
- 队列项是 `WatchTarget(knowledge_id, parts)` —— `parts` 为空是整个知识点，非空是它底下的一片，**知识点和分片走同一个队列**。启动时按和自动模式一样的顺序装载（`_load_watch_queue()`），上次已经 `slicing` 的知识点直接从没采完的分片接着排。把浏览器带到队首的**续采页**（不是第 1 页），队首一变就自动跳过去。
- `_advance_queue()` 每入库一页跑一次，判据和自动模式完全一样，只是"翻页"由人做：**超硬顶 → `_expand_into_slices()` 就地把这一项换成下一维的若干子片**（题型→难度→解答题子题型→年份，按需展开不预先铺开）；**页码覆盖满 → `_finish_item()` 标 done、重算 collected、弹出队列**；四维用尽还超 → `capped`。一个知识点的分片全出队后 `_maybe_rollup()` 汇总回 `knowledge_tree`，**任一片 `capped` 整个知识点就标 `capped`**。
- 超硬顶必须提示：不提示的现象非常隐蔽 —— 人一页页翻到第 999 页，进度一直涨，但 `is_fully_covered()` 对超硬顶的行永远返回 False，这个知识点会挂在 `partial` 上到天荒地老。★ 这是 watch 模式下脚本唯一会做的导航动作，每个知识点一次；`ZUJUAN_WATCH_AUTO_OPEN = False` 可以关掉，关掉后日志照样打出下一个该采的地址。
- 完成判定用 `slicing.is_fully_covered()`：**判据是"该翻的页都翻过了"而不是"库里的数够了"** —— 站点随时新增题，用 `collected >= site_total` 当条件永远差最后几道判不完。`site_total` 未知、或超过翻页硬顶时一律不判 done（前者会把没采的标成采完，后者翻页本来就覆盖不完）。采完写 `scrape_status='done'` 并重算 `collected`。
- 每页入库后重算一次 `collected`（`refresh_collected()`，**重算不是累加** —— 采集可以重跑，且一题挂多个知识点）。
- 进度和自动模式共用 `knowledge_tree` / `knowledge_slice`，只累加 `covered_pages` / `last_page` / `site_total`。★ **`_write_page_progress()` 不会把已经 `done`/`capped`/`empty` 的状态降级** —— 人重新浏览一个采完的知识点，不该把它打回"采了一半"；`site_total` 为 `None` 时整列跳过，不能拿 0 冲掉已知值。

### 组卷网按知识点抓取

`ZUJUAN_CRAWL_MODE = "knowledge"` 时，待办清单来自另外两张外部表：`knowledge_tree`（1696 个节点，其中 1325 个叶子）和 `knowledge_slice`（切片进度）。口径由 `docs/zujuan/知识点树抓取规范.md` 和 `知识点切片抓取规范.md` 定死。策略计算全在 `media_platform/zujuan/slicing.py`（纯函数、不碰网络和数据库），进度读写在 `store/zujuan/_progress.py`。

- **只抓叶子**（`child_count == 0`）。父节点的列表页包含它全部子孙的题，采父节点等于把子节点重复翻一遍。`knowledge_tree` 也是共享表，树结构那一组列归"知识点树同步"那条线，本项目只写 `_progress.py` 里 `TREE_PROGRESS_COLUMNS` 白名单内的 8 个进度列 —— 出现别的列直接抛错（`questions` 用"ORM 不声明"兜底，这张表必须能读结构列，所以改成白名单校验）。
- **翻页硬顶 999 页 = 9990 道，且是 per-URL 的**。第 1000 页起服务端不报错、不返回空页，而是把第 999 页原样重复返回 —— 表现是"程序在跑但入库数不涨"。检测靠**比较相邻两页的题目 ID 列表**，完全相同就是撞顶。要和"这一页没有卡片"（正常翻到底）区分开，两者处置完全相反。
- **读不到 `#questioncount` 不等于没题**。`extract_site_total()` 返回 `None`（读不到，多半被拦截或页面结构变了）和 `0`（站点明说没题）是两件事：`None` 必须原样保留"还没翻完"下次重试，误判成"翻完了"这个知识点后面的题就永远不会再被采集。
- **"这一页没有题目卡片"同样不等于翻到底**，必须拿它和 `site_total` 对一下：站点说共 66 页却在第 9 页读回来零张卡片，这两个数据自相矛盾，只能保留 `partial` 下次重试。线上 zsd6026 就是被无条件当成"翻到底了"标成 `done` 的 —— 一个才翻了 8 页、只有 159 道的知识点被记成采完，剩下 57 页再也不会被采集，而且不报错。三条相关规则：① 空页且 `page < total_pages(site_total)` 先原地重取 `EMPTY_PAGE_RETRY` 次（列表是 domcontentloaded 之后由 JS 填进 DOM 的，网慢时取早了拿到的是"有 `#questioncount`、零张卡片"的半成品，它照样能通过 `page_status()`）；② 重取完还是空就返回 `INTERRUPTED`，**绝不能是 `DONE`**；③ `total_pages()` 封顶 999，所以超硬顶的片"翻到最后一页"其实是撞上了硬顶，走 `NEED_SLICE` 而不是 `DONE`。
- **浏览器取页必须等卡片进 DOM**（`client._wait_for_list_rendered()`），`goto(wait_until="domcontentloaded")` 之后立刻 `page.content()` 就是上面那个半成品的来源。点击翻页那条路径（`_wait_page_changed()`）同理：判据是"新的一页真的有卡片"，不能只看 `first_question_id` 和上一页不一样 —— AJAX 换页时列表会先被清空，那一瞬间它是 `None`，`None != 上一页的 ID` 也算"换掉了"。
- **超过硬顶就切片**，读到数字的第一时间就转，不用傻等翻到第 999 页。级联维度固定顺序：题型(5) → 难度(3) → 解答题子题型(5，★只有解答题有这一维) → 年份(8)。某一维在当前条件下不存在要**跳过去找下一个**，不能判定"切不动了"。按需下钻，不预先展开。四维用尽仍超 → `capped` 终止，等人工判断。
- **`slice_key` 短码和 URL 站点码是两套命名空间**（`knowledge_slice` 的 DDL 注释说"和 URL 里的段一模一样"是错的）：`t1→qt1101` `t2→qt1104` `t3→qt1102` `t4→qt1103` `t5→qt1105`，难度 `d1/d2/d3` 两边一样，子题型 `s1..s5` → **粘在题型码后面的两位** `01..05`（`qt1103`+`05`=`qt110305`），年份 `y2020..` / `y-1`。拼接顺序固定按维度顺序，顺序一变断点续采就查不到上次那一行，会把整个知识点从头再切一遍。
- **`depth` 存的是维度在级联里的序号**（qtype=1 difficulty=2 sub_type=3 year=4），不是"实际切了几层" —— 单选题跳过了子题型，它底下的年份片 depth 仍是 4。线上 407 行历史数据就是这个口径（文档 5.1 节的说法与之不符，以数据为准）。
- **`collected` 必须重算不能累加**（采集可重跑，且一题挂多个知识点）。切片的 recount 用 `questions.difficulty_band`（得分率重算的 3 档）对应 `d1/d2/d3`，**不是** `difficulty_code`（按钮上的 5 档）—— 两套编码数值会撞车。只重算叶子知识点和真正翻过页的片；被再往下切的父片不重算（线上数据也是 `collected=0`）。
- **`covered_pages` 写成逐页逗号分隔**（`1,2,3,5`），不做区间压缩 —— 补采时要一眼看出中间缺了哪几页，区间格式得先在脑子里展开。读的时候两种格式都认（老数据是 `1-281`，`tools/zujuan_progress_fix.py` 已把线上 14 行转过来了）。翻页硬顶 999 页，写满也就 3887 字符，这一列是 TEXT；`expand_page_ranges()` 会丢掉 >999 的页码，免得脏值撑爆它。`slicing.missing_pages()` 直接给出还缺哪几页。
- **续采起点取 `covered_pages` 的第一个缺口**，`covered_pages` 为空才退回 `last_page + 1`。线上 `zsd5930` 就是 `last_page=317` 但 `covered_pages='1-281'`，按 `last_page+1` 续采会静默跳过 282~317 共 36 页且再也不会回头补。
- **每翻完一页立刻写进度并提交**，中断最多丢当前这一页。子片状态汇总：任一片 `capped` → 父片也 `capped`（让人知道确实有一部分拿不全）；全部 `done`/`empty` 才算 `done`；还有片没跑完保留 `slicing`。
- 每页之间、每个知识点之间的等待都在 `ZUJUAN_PAGE_SLEEP_RANGE` / `ZUJUAN_KNOWLEDGE_SLEEP_RANGE` 区间里**随机取** —— 固定间隔本身就是机器特征。本次运行的入库预算走 `ZUJUAN_MAX_QUESTIONS_PER_RUN`，不看 `CRAWLER_MAX_NOTES_COUNT`（那个默认才 50）。
### 组卷网浅采（广度优先铺底）

`ZUJUAN_MAX_PAGES_PER_KNOWLEDGE > 0` 时进入浅采：每个知识点只翻前 N 页就换下一个，用来给全部知识点铺一层底，**顺带把每个知识点的 `site_total` 摸出来**（第 1 页就能读到"共计 N 道试题"，这是浅采最主要的产出）。配 `ZUJUAN_ONLY_UNCRAWLED`（只挑 `scrape_status='none'`）和 `ZUJUAN_EXCLUDE_PATHS`（按 `path` 关键字排掉整个分支）使用。

- **提前停必须落 `partial`，绝不能是 `done`** —— 只翻了 N 页却标成"采完了"，这个知识点后面的题就再也不会被采集，而且不报错（和 `site_total` 误判成 0 是同一类静默数据损坏）。复用 `SliceOutcome.INTERRUPTED`（值就是 `"partial"`），语义正好，不新增枚举值。
- **★ 页数预算的判断放在 `_page_through()` 循环底部**，在"这一页没卡片"和"`page >= total_pages`"两个收尾判断**之后**。放到循环顶部的后果是站点只有 3 页的知识点也被记成 `partial`，永远采不完 —— 同样不报错。边界上"翻完了"优先于"预算到了"。
- 预算算的是**本轮翻了几页**（`page - first_page + 1`）不是"翻到第几页"，所以从第 3 页续采仍然翻满 N 页。
- **浅采模式关掉超量切片**，两者是绑定的：浅采的意义是广度优先铺底，当场为某个知识点炸出一堆分片去挨个采正好相反。三条路径都要堵：首页读到超硬顶（在循环里就地放行，照样翻够 N 页）、翻页中途才发现超硬顶、以及上次已经 `slicing` 的知识点（直接跳过，它手里的题远不止这几页）。留 `partial` 等以后深采时再切，代价是这 N 页没记进任何分片的 `covered_pages`，将来重翻一次。
- **`fetch_leaf_targets()` 的两个新过滤都下推到 SQL**，不能取回来再在 Python 里筛 —— `limit` 是在数据库侧生效的，先 limit 后筛会让 `--knowledge_limit 50` 实际拿到不足 50 个。`path NOT LIKE` 要显式放行 `path IS NULL`，否则 path 为空的节点会被顺手滤掉。
- 续跑是白送的：浅采过的知识点状态变成 `partial`，`ZUJUAN_ONLY_UNCRAWLED` 只挑 `none`，中断了直接再跑一遍即可。第 1 页就没成功的仍是 `none`，下轮自然会重试。

- `media_platform/zujuan/core.py` 和 `store/zujuan/_progress.py` **互相依赖**（爬虫写进度，进度层用切片维度定义），靠 core.py 顶部的 `from __future__ import annotations` 让 import 期间不去取对方属性化解。不要在 core.py 的模块层直接取 `progress.X`。

阿里云 WAF 是阶梯式升级的（放行 → JS 挑战 → 人机验证 → 限流），而**被拦的页面同样返回 HTTP 200**，不检测就会被当成空页静默写入空数据。所以 `help.py::page_status()` 把页面判成四态 `PageStatus`，`ZuJuanClient.get_page_html()` 据此分级处置：`JS_CHALLENGE`/`UNKNOWN` 退回浏览器重取（浏览器的结果是权威的，它都没看到题又没有拦截特征才算真空页）；`CAPTCHA` 走 `wait_human_solve()`，把页面 `bring_to_front` 后等人拖滑块，过完自动把新 Cookie 同步回 httpx；HTTP 429 按 `5*2^n + 抖动` 指数退避重试。判定顺序是**先用"有没有题目卡片"正向确认成功**，剩下的才逐层匹配拦截特征——新增判定条件时要保持这个顺序，否则正常页面里出现关键词就会被误判。人机验证需要 `CDP_HEADLESS`/`HEADLESS = False`，无头模式下直接报错而不是干等。

**"浏览器过验证 + httpx 翻页"这套要成立，httpx 必须装得和那个浏览器是同一个客户端**，否则凭证一到 httpx 手里就失效，症状是"人手动过一次滑块，之后每翻一页都要再过一次"。四条缺一不可：

- **同一个 User-Agent**。`core.py::_read_browser_fingerprint()` 从页面读真实的 `navigator.userAgent`，不能用 `utils.get_user_agent()` 那个随机假 UA —— CDP 接管已有 Chrome 时 `CDPBrowserManager._create_browser_context()` 走的是 `browser.contexts[0]` 分支，传进去的 `user_agent` 参数**被静默忽略**，浏览器用的始终是它自己的真 UA。WAF 把过完滑块的凭证绑在客户端指纹上，换个 UA 拿同一张凭证会被判成盗用并立刻重新验证。
- **持久的 Cookie jar**。`ZuJuanClient._get_client()` 维护一个长生命周期的 `AsyncClient`（只在代理变了时重建，并把 jar 带过去），不能每次请求 `async with make_async_client(...)` 用完即弃 —— WAF 的 `acw_tc` 几乎每个响应都轮换，丢掉 `Set-Cookie` 就等于一直在重放过期凭证。
- **只带本域 Cookie**。`browser_context.cookies(urls=[ZUJUAN_HOST])` 必须带 `urls`；不带时 Playwright 返回整个上下文里所有域的 Cookie，CDP 接管的又是用户真实的 Chrome，那等于把用户其它网站的登录态发给组卷网，几十 KB 的 Cookie 头本身也是明显的异常特征。
- **`sec-ch-ua` 用页面真实报的 `navigator.userAgentData.brands` 拼**，取不到就不发。Chrome 的品牌列表里有一项是每版都变的 GREASE 值，照 UA 里的版本号猜一套出来比不发这个头更像机器。同理 `Accept-Encoding` 只声明 `httpx._decoders.SUPPORTED_DECODERS` 里真能解的（没装 brotli 还声明 `br`，服务端真返回 br 时解出来是二进制乱码，会被 `page_status()` 判成 UNKNOWN 甚至空页）。

### 组卷网 api 取页模式（`ZUJUAN_FETCH_MODE = "api"`）

站点分页器点下去打的是 `POST /zujuan-api/question/list`，返回 `{"code":"0","data":{"html":..., "total":677}}`。`data.html` 是一段只含 `div.tk-quest-item` 的片段，**和整页渲染出来的卡片结构逐字节一致**，`ZuJuanExtractor` 不用改一行就能解析（`media_platform/zujuan/test_data/zujuan_api_list.json` 存了一份线上真实响应，`tests/test_zujuan_api.py` 拿它把 35 个字段全锁住了）。省掉渲染，每页只有 9 KB 左右。参数拼装和响应解析在 `media_platform/zujuan/api.py`，和 `slicing.py` 一样是纯函数。

- **★ 唯一必须补的缺口：`site_total`。** `#questioncount`（"共计 N 道试题"）和 `div.tk-pager` 都是**页面外壳**，不在片段里，`extract_site_total()` 对它一律返回 `None` —— 而 `None` 在 `_page_through()` 里的含义是"这一趟没读到，保留 partial 下次重试"。照搬接口会让每个知识点在第 1 页就中断，一道题也采不到。题数改从 `data.total` 取。
- **每一片的首页仍然走浏览器**，之后的页才走接口。那一趟本来就要做：过 WAF 挑战、刷新 Cookie、读防伪令牌、读 `#questioncount`，接口一样都给不了。一片动辄几百页，摊到每页的浏览器开销可以忽略，风控处置那一整套却原样保留了下来。
- **`curPage` 是 1 基，而且是"要去的那一页"**（2026-09 实测）。线上抓到的请求里 `curPage=67` 配 Referer `o2p68` 看着像 0 基，实际是人停在第 68 页点了"67"那个页码 —— Referer 只是从哪儿来的。这条记录很容易看反。
- **★ 用接口之前必须过对齐校验**（`core._api_aligned()`）：拿浏览器刚取到的那一页，用同一个页码再走一次接口，比题目 ID 列表和题数。页码基数已经证实了，**但 `quesType`/`quesDiff`/`quesYear` 的映射仍然是照 URL 段码推的、没验证过** —— 推错了不会报错，只会让筛选条件被忽略，把整个知识点的题当成某个分片入库（现象是接口返回的 `total` 等于知识点总数）。这才是这道校验现在真正在守的东西。校验不过就整轮关掉接口退回浏览器，慢但不写坏数据。代价是每片一次额外请求，不到 1%。
- **维度码只有一份真相**：`api.py` 的三个 `*_value()` 直接从 `slicing.SliceValue` 取，不另抄一张表。子题型仍是**粘在题型码后面的两位**（`1103` + `05` = `110305`），和 `url_filter_segment()` 的拼法一致；难度是 URL 段码去掉 `d`；`y-1`（更早以前）→ `-1`。
- **认不出一律返回 `None` 退回浏览器**，绝不当成"这一页没题"。被 WAF 拦下时接口返回的是 HTML 而不是 JSON，`parse_response()` 判成 None，令牌也一并丢弃下次重读；返回体里有验证码特征时照样抛 `CaptchaPageError` 走人工。空 `html` 配非零 `total` 是**合法**结果（翻过了最后一页），交给上层按页数判。
- **`RequestVerification` 请求头和 `__RequestVerificationToken` Cookie 不是一个值**（ASP.NET Core 的防伪令牌是密码学配对的两半），只能用 `client.read_verification_token()` 从页面 DOM 里读，读不到就不许走接口。人过完验证之后页面换过文档，令牌一并作废（`forget_verification_token()`）。
- **每页条数改不了**：实测传 `pageSize=50` 站点直接忽略，照样返回 10 条，别再试了。`ZUJUAN_API_PAGE_SIZE` 这个开关留着只为守住一件事 —— 只允许 0 或 `slicing.PAGE_SIZE`，填别的在 `start()` 里直接报错。`covered_pages` 里几十万条页码都是按 10 条一页记的，页大小一变这些进度全部失去意义（50 条一页的第 5 页和 10 条一页的第 5 页不是同一批题），断点续采会静默跳页或重复。换页大小是一次独立的数据迁移，不是一个开关。同理翻页硬顶 999 页 = 9990 道也是跟着页大小走的。
- 空页重取（`_refetch_empty_page()`）一律走 `get_page_html`（api 模式下就是浏览器）而不是接口 —— 浏览器那一趟的结果是权威的。

**浏览器翻页优先"点分页器"而不是直接 `goto` 深链接**（`ZUJUAN_HUMAN_PAGING`，默认开）。连续 `goto` 几百个 `/o2p387/` 深链接没有导航链、也不触发站点自己的翻页 JS，和真人翻页完全是两条路径；点 `a[data-type="switchPage"]` 才是站点期望的那条。整套还可以用 `ZUJUAN_FETCH_MODE = "browser"` 切成全程走浏览器（慢很多，但 httpx 的 TLS 指纹和 Chrome 不同，换 UA 也补不平这一层）。

分页器真实结构见 `media_platform/zujuan/test_data/zujuan_pager.html`（2026-09 从线上取的），三个反直觉的点：**当前页是 `<a data-num="1" class="… active">`**（用 `data-num` 读页码，别解析文本）；**"下一页"是个没有文本的图标按钮** `<a title="下一页" data-type="nextPage">`，`:has-text("下一页")` 永远匹配不到；分页器 `data-cap="10"` 一次只显示 10 个页码，**要到远处的页只能用站点自带的跳转框** `#iptGotoNum` + `a[data-type="confirmGoto"]`（`_jump_via_input()`）。定位顺序：页码链接 → 下一页（仅相邻）→ 跳转框 → `goto`。

★ `a#lastpage` 的 `lastid` 会**严重少报**：`data-sum=2415435`（24 万页）的页面上 `lastid` 只写 100，而库里存在 `last_page=991` 的记录。`extract_total_page()` 以 `data-sum/data-size` 算出来的为准、取两者较大值并封到 999 —— 信了 `lastid` 会在第 100 页判定"翻完了"，静默漏掉后面的题。

点击翻页最大的风险是**点错链接却不报错**，所以 `_try_click_paging()` 点完必须用 `current_page_from_pager()` 或 `page.url` 确认真的到了目标页，确认不了一律返回 `None` 退回 `goto` —— 拿错页的题当第 N 页入库并记进度是不报错的静默数据损坏。找不到分页器链接时会把 `div.tk-pager` 的真实结构打进日志（只打一次）好补选择器。人过完验证后 `_browser_base_url` / `_browser_page_no` 必须清空，因为验证过程中页面跳转过，"停在第几页"已经不可信。

**人过完验证之后有一段"只走浏览器"的冷却期**（`_enter_browser_cooldown()`，基础 60s，连续被挑战按 2 的幂增长封顶 600s，httpx 恢复正常立刻解除）。刚过完验证时 WAF 对这个 IP 处在高度戒备，而 httpx 和 Chrome 的 TLS 指纹本来就不同，这时候立刻用 httpx 硬打只会把风控等级越推越高。

签名方式各平台不同：小红书有纯 Python 实现（`xhs_sign.py`，另有 `playwright_sign.py` 作为在页面内执行 JS 的兜底方案）；抖音和知乎用 `execjs` 编译 `libs/douyin.js` / `libs/zhihu.js`（这也是必须装 Node 的原因）；其余平台通过浏览器求值表达式签名。标准 Playwright 模式下会以 init script 注入 `libs/stealth.min.js`。

### 浏览器模式

`ENABLE_CDP_MODE = True`（默认）通过 `tools/cdp_browser.py::CDPBrowserManager` 用 DevTools 协议连接用户真实的 Chrome —— 要么接管已开启远程调试的浏览器（`CDP_CONNECT_EXISTING`），要么启动由 `tools/browser_launcher.py` 探测到的浏览器。这种方式复用了真实 Cookie 与扩展，风控检测风险更低。设为 `False` 则回退到 `launch_browser()`，按平台使用各自持久化的 `USER_DATA_DIR`。`AbstractCrawler.launch_browser_with_cdp()` 有默认实现会降级到 `launch_browser()`，所以新平台严格来说只需实现后者。

### 存储层

两套并行的分发机制，都以 `config.SAVE_DATA_OPTION` 为键（`csv | json | jsonl | db | sqlite | postgres | mongodb | excel`）：

- `store/<平台>/__init__.py` —— `<Platform>StoreFactory` 把存储选项映射到实现类，另外提供模块级的 `update_<平台>_note/comment/...` 协程。爬虫只调用这些模块级函数：它们把平台原始 JSON 归一化成扁平 dict，再交给工厂选出的 store。
- `store/<平台>/_store_impl.py` —— 具体的 CSV/JSON/JSONL/DB/SQLite/Mongo/Excel 实现类。`db` 与 `postgres` 共用同一个 SQLAlchemy 实现，`sqlite` 继承自它。

文件类输出经 `tools/async_file_writer.py` 落到 `data/<平台>/<csv|json|words>/…`。Excel 先在内存中缓冲，退出时统一落盘（`ExcelStoreBase.flush_all()`）。SQL 存储使用 `database/models.py` 中的异步 SQLAlchemy 模型，引擎在 `database/db_session.py` 中按数据库类型缓存；选择数据库存储时 `main.py` 会自动建表。

### 支撑模块

`proxy/` —— `create_ip_pool()` 从某个 provider 构建经过校验的 `ProxyIpPool`（`kuaidaili`、`wandouhttp`、`static`；`jishu_http_proxy.py` 虽然存在，但未注册进 `IpProxyProvider`）；client 通过混入 `ProxyRefreshMixin` 在代理过期前轮换。`cache/` —— `CacheFactory.create_cache("memory"|"redis")`。`api/` —— WebUI 的 FastAPI 后端，其 `services/crawler_manager.py` 以**子进程**方式运行爬虫（`uv run python main.py …`）并把 stdout 通过 WebSocket 推给前端，并不在进程内 import 爬虫。

## 仓库不变量

**不采集、不落库任何用户个人信息。** 本版本在七个平台上统一移除了 PII：原始用户 ID 经 `tools/user_hash.py::anonymize_user_id` 转成 `creator_hash`（sha256 截断 16 位十六进制），昵称用 `mask_nickname` 做中间脱敏，IP 归属地、头像、主页链接、个性签名、性别以及粉丝/关注列表一律不采集；`database/models.py` 中各平台的 creator 档案表已被删除。这一约束由测试强制保障，`tests/test_no_user_info.py` 会自省 ORM 是否含禁用列，并 grep `store/` 目录是否写入了禁用字段键——任何新字段、新模型或新平台若违反此约束都会让测试失败。

**每个 Python 文件都必须带项目版权头。** `tools/file_header_manager.py`（已接入 `.pre-commit-config.yaml`）会检查并自动插入文件头，其中的 GitHub 链接包含该文件自身的路径。新增 `.py` 文件必须带上，可执行 `python3 tools/file_header_manager.py <文件>` 补齐，或交给 pre-commit 自动修复。

## 新增一个平台

按顺序需要改动：`cmd_arg/arg.py`（`PlatformEnum` 以及两条 ID 列表分发链）→ `config/<名称>_config.py`（并在 `base_config.py` 中星号导入）→ `media_platform/<名称>/{core,client,login,field,help,exception}.py` → `model/m_<名称>.py` → `database/models.py`（内容表 + 评论表，带 `creator_hash`，不得有 PII 列）→ `store/<名称>/{__init__.py,_store_impl.py}`（工厂映射要写全）→ `main.py::CrawlerFactory.CRAWLERS`。
