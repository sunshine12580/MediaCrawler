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

例外是 `media_platform/zujuan/`：组卷网列表页无需登录，因此没有 `login.py`，`help.py` 里放的是 HTML 解析器 `ZuJuanExtractor` 而不是签名逻辑。它在 CDN 层有阿里云 WAF，直接 httpx 请求只会拿到挑战脚本，所以 `core.py` 先用浏览器打开一次首页过挑战，再把 Cookie 交给 httpx 翻页。该平台只支持 `--type search`（按列表页 URL 抓题并翻页），答案与解析需要登录才可见，未登录时字段为空。

阿里云 WAF 是阶梯式升级的（放行 → JS 挑战 → 人机验证 → 限流），而**被拦的页面同样返回 HTTP 200**，不检测就会被当成空页静默写入空数据。所以 `help.py::page_status()` 把页面判成四态 `PageStatus`，`ZuJuanClient.get_page_html()` 据此分级处置：`JS_CHALLENGE`/`UNKNOWN` 退回浏览器重取（浏览器的结果是权威的，它都没看到题又没有拦截特征才算真空页）；`CAPTCHA` 走 `wait_human_solve()`，把页面 `bring_to_front` 后等人拖滑块，过完自动把新 Cookie 同步回 httpx；HTTP 429 按 `5*2^n + 抖动` 指数退避重试。判定顺序是**先用"有没有题目卡片"正向确认成功**，剩下的才逐层匹配拦截特征——新增判定条件时要保持这个顺序，否则正常页面里出现关键词就会被误判。人机验证需要 `CDP_HEADLESS`/`HEADLESS = False`，无头模式下直接报错而不是干等。

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
