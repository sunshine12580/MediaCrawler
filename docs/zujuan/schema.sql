-- 组卷网题库表结构（从生产库 SHOW CREATE TABLE 导出，是权威版本）
-- 组卷网写的是这三张已有的表，MediaCrawler 不会自动建表：
-- config/zujuan_config.py 里 ZUJUAN_AUTO_CREATE_TABLES = False。
-- ★ questions 是多阶段共享的大表，抓取阶段只写其中 35 列，
--   answer_* / stem_md / render_status 等列归其它阶段，抓取时一列都不许碰。

CREATE TABLE `questions` (
  `question_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '题目 ID（卡片 questionid 属性）。去重的地基，绝不能用每次渲染都变的 data-sys-id',
  `grade` varchar(8) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '学段：middle=初中(czsx) / high=高中(gzsx)。知识点 ID 分学段，两边不通用',
  `knowledge_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '主知识点 ID（如 zsd4700）。一题多知识点见 question_knowledge 表，筛题走那张',
  `knowledge_tags` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '全部知识点名称的 JSON 数组，仅供查看。JSON 建不了索引，不要用来筛题',
  `source` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '来源试卷全名（卡片 questitle 属性）',
  `qtype` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '题型名：单选题/多选题/填空题/解答题/判断题',
  `difficulty` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '卡片难度名（5 档：容易/较易/适中/较难/困难）。与筛选用的 3 档不是同一套',
  `score_rate` double DEFAULT NULL COMMENT '得分率（卡片 qdvalue），越大越简单。difficulty_band 的原始依据',
  `year` int DEFAULT NULL COMMENT '年份。优先取 title_abbr 解析出的学年起始年，取不到才从来源标题正则抠',
  `stem_html` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '题干原始 HTML（div.exam-item__cnt 的 innerHTML）',
  `stem_md` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '★完整题目的 Markdown（题干 + 选项），和 stem_html 口径一致。公式 $latex$、插图 ![](本地路径)。只要题干不要选项用 stem_body_md',
  `stem_status` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'none' COMMENT '题干进度：none / html_saved / md_done。★加新取值必须同步改 store.decide_action()',
  `answer_img` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '答案图本地相对路径。★本地这张图是唯一持久副本 —— 看过一次站点也不会再免费给，永不重下',
  `answer_md` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '答案 OCR 结果（离线产物，改 prompt 可整批重跑）',
  `answer_status` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'none' COMMENT '答案进度：none / retry(没拿到，下次再试) / got_image / ocr_done / no_answer(站点确实没答案，永不再试)。★retry 与 no_answer 后续动作相反，混了会永久丢数据',
  `list_url` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '这道题是在哪个列表页抓到的。--resume 补答案时按它回查',
  `raw_day` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '题干原始 HTML 存在 data/raw/ 里哪一天的文件。★一天可能有多个分片（<raw_day>.jsonl / <raw_day>.002.jsonl …），满 2 万行开下一个',
  `first_seen_at` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '第一次见到这道题的时刻。upsert 时不会被改写',
  `stem_at` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '题干最后一次写入时刻',
  `answer_at` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '答案最后一次写入时刻',
  `bank_id` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '题库编号（初中数学=2）。拼答案图/详情页 URL 必需：getAnswerAndParse/{question_id}/{bank_id}/…',
  `title_abbr` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '卡片 titleabbreviation 原串，如 25-26七年级上—湖南湘潭—期中。★保留原串，解析规则改了可离线重跑',
  `school_year` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '学年，如 2025-2026。来自 title_abbr 第 1 段',
  `grade_level` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '年级：六/七/八/九年级。来自 title_abbr 第 1 段',
  `term` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '学期：上学期/下学期。来自 title_abbr 第 1 段',
  `province` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '省份。来自 title_abbr 第 2 段；省市之间无分隔符，靠省份表最长前缀切开',
  `province_code` varchar(8) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '省级行政区划码（GB/T 2260），如湖南=430000',
  `city` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '地级市。直辖市为空（省即市，不编造市名）',
  `source_type` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '来源类型：期中/期末/中考真题/竞赛…。来自 title_abbr 第 3 段，词表比筛选那 17 项多（如「模拟预测」）',
  `difficulty_code` varchar(8) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '卡片 qdid（5 档）。★与筛选 URL 的 d 段撞号：qdid=2 是较易，d2 是适中，不可混用',
  `difficulty_band` varchar(8) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '筛选口径的 3 档，由 score_rate 算：1.0≥容易>0.8≥适中>0.5≥困难>0。按站点口径查询用这列',
  `qtype_code` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '题型码。初中：单选1101 多选1104 填空1102 解答1103 判断1105；高中另一套码',
  `category_id` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '所属章节 ID（卡片 categoryid）',
  `category_name` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '所属章节名（卡片 categoryname），如「有理数」',
  `paper_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '主来源试卷 ID。一题多卷见 question_sources 表',
  `used_count` int DEFAULT NULL COMMENT '被组卷引用次数（卡片上的「23次组卷」）',
  `is_famous_school` tinyint DEFAULT NULL COMMENT '是否带「名校」标签：1=是 0=否',
  `qtype_full` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '完整题型原串「解答题-计算题」。★按钮属性 qyname 只有大类，子类型只在卡片第一个 span.info-cnt 的文字里',
  `qtype_sub` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '题型的细分，从 qtype_full 按 - 拆出来。解答题→计算题/作图题/应用题/证明题/问答题（★这五档是切片维度 sub_type，见 urls.SUB_TYPE_CODES）；多选题→2/3/4个答案（量小，不用来切片）',
  `orig_no` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '这道题在**原试卷**里的题号（"20"）。题干开头本来带着它，剥出来单独存 —— 组卷时会有新编号，正文里留着旧的很怪',
  `stem_text` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '★完整题目的纯文本（题干 + 选项），和 stem_html 口径一致。公式是裸 LaTeX 源码、插图是 [图N] 占位。给检索和喂模型用',
  `render_status` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'md/text 的生成进度：none / md_done / text_done / failed。★和 stem_status 分开 —— 那个说原料有没有，这个说加工到哪一步',
  `blank_count` int DEFAULT NULL COMMENT '填空题的空数，数 <bk> 标签。站点的空位是结构化的：<bk index="1" type="underline">',
  `sub_question_cnt` int DEFAULT NULL COMMENT '解答题的小问数，数题干里的 (1)(2)(3)。实测 24/41 道解答题有 2~5 个小问',
  `option_count` int DEFAULT NULL COMMENT '选项个数，数 optionsTable 里的 <td>。详细内容在 question_options 表',
  `stem_html_local` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '题干 HTML，但 <img src> 换成本地路径 data/images/…。原始的 stem_html 保持站点原样不动 —— 那是原料，图片重下/换目录都不该改到它。★选择题的它同样含选项表',
  `stem_body_html` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '★纯题干 HTML：从 stem_html 里剥掉 <table name="optionsTable"> 之后的部分。选择题的 stem_html 是题干+选项连在一起的，而 stem_md/stem_text 已经剥了选项——这一列让 HTML 那一路和它们口径一致。非选择题与 stem_html 相同',
  `stem_body_html_local` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '纯题干 HTML + 图片本地路径。渲染一道选择题的正确组合：stem_body_html_local（题干）+ question_options.content_html_local（各选项）',
  `stem_body_md` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '纯题干的 Markdown（不含选项）。选择题排版时题干和选项要分开渲染，用这个 + options_md',
  `stem_body_text` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '纯题干的纯文本（不含选项）',
  `options_html` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '整块选项的原始 HTML，就是从 stem_html 末尾切下来的 <table name="optionsTable"> 那一段。非选择题为空',
  `options_html_local` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '整块选项 HTML + 图片本地路径。★94/125 组选项含图，不本地化离线渲染就是空白',
  `options_md` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '整块选项的 Markdown，一行一个「A. 内容」。逐个选项另见 question_options 表',
  `options_text` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '整块选项的纯文本，一行一个「A. 内容」',
  `stem_hash` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '题干 HTML 的 md5 前 32 位。重采时拿它比对：一样就整行跳过，不一样才更新题干并重置 render_status 让解析重跑',
  `is_real_exam` tinyint DEFAULT NULL COMMENT '是否带「真题」标签：1=是 0=否。★和 source_type=中考真题 不是一回事 ——那个来自 title_abbr 第 3 段（试卷类型），这个是卡片上的角标',
  PRIMARY KEY (`question_id`) USING BTREE,
  KEY `idx_q_answer` (`answer_status`) USING BTREE,
  KEY `idx_q_knowledge` (`knowledge_id`,`qtype`,`difficulty`) USING BTREE,
  KEY `idx_q_source` (`source_type`,`grade_level`,`term`) USING BTREE,
  KEY `idx_q_area` (`province_code`,`city`) USING BTREE,
  KEY `idx_q_band` (`difficulty_band`,`score_rate`) USING BTREE,
  KEY `idx_q_paper` (`paper_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='题目主表：一道题一行，用 stem_status/answer_status 表达进度，不拆成题目表+答案表';

CREATE TABLE `question_knowledge` (
  `question_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '题目 ID。主键之一',
  `knowledge_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '知识点 ID（zsd 编号）。主键之一',
  `knowledge_name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '知识点名称，冗余存一份，查询时免去再连知识点树',
  `ord` int DEFAULT '0' COMMENT '在卡片上的先后顺序，0 是主知识点',
  PRIMARY KEY (`question_id`,`knowledge_id`) USING BTREE,
  KEY `idx_qk_knowledge` (`knowledge_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='一题多知识点关联表。解析产物，先删后插，可整批重跑';

CREATE TABLE `question_sources` (
  `question_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '题目 ID。主键之一',
  `paper_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '来源试卷 ID，详情页 /{bank_id}p{paper_id}.html。主键之一',
  `paper_title` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '试卷全名',
  `ord` int DEFAULT '0' COMMENT '顺序，0 是卡片上显示的那套主来源',
  PRIMARY KEY (`question_id`,`paper_id`) USING BTREE,
  KEY `idx_qs_paper` (`paper_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='一题多来源试卷关联表。卡片文案是「N 卷引用」，一题可被多套试卷收录';

-- ===========================================================================
-- 按知识点抓取用的两张表（同样是从生产库 SHOW CREATE TABLE 导出）
-- knowledge_tree 是共享表：树结构那组列归"知识点树同步"那条线，
-- 抓题这条线只写 is_leaf / scrape_status / site_total / collected /
-- last_page / covered_pages / scraped_at / note 这 8 个进度列
-- ===========================================================================

CREATE TABLE `knowledge_tree` (
  `knowledge_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '知识点 ID，★统一带 zsd 前缀（zsd4700）。树 JSON 里是纯数字，这里补上前缀才能和 questions.knowledge_id 对上',
  `node_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '树 JSON 里的原始数字 ID（4700），不带前缀',
  `bank_id` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '学科库编号。初中数学=2（1语文 2数学 3英语 4物理 5化学 6生物 7政治）',
  `title` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '知识点名称',
  `parent_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '父节点 knowledge_id，同样带 zsd 前缀。根节点为空',
  `level` int DEFAULT NULL COMMENT '层级，根=0。初中数学最深 5 层',
  `path` varchar(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '从根到本节点的完整标题路径，如「初中数学综合库 / 数与式 / 有理数 / 相反数」',
  `href` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '站点链接 /czsx/zsd4700',
  `is_knowledge` tinyint DEFAULT NULL COMMENT '站点的 isKnowledge 标记，实测全树都是 1',
  `child_count` int DEFAULT NULL COMMENT '直接子节点数，0 表示叶子（真正用来打标签的那层）',
  `sort_ord` int DEFAULT NULL COMMENT '在同级里的顺序，保持站点原始排列',
  `updated_at` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '本行最后一次同步时刻',
  `is_leaf` tinyint DEFAULT '0' COMMENT '是不是叶子节点（child_count=0）。★采集只走叶子：父节点页面包含全部子孙的题，采父节点等于把子节点又采一遍',
  `scrape_status` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'none' COMMENT '采集状态：none 没采过 / partial 采了一半（下次从 last_page+1 接着采）/ slicing 题太多，已改成按题型切片采，进度在 knowledge_slice 表 / done 采完了 / capped 切到底仍超过翻页硬顶，还有题拿不到 / empty 站点说这里没题',
  `site_total` int DEFAULT NULL COMMENT '站点说这个知识点有多少道题（列表页 #questioncount）。每次采集刷新，会随站点增题而变大',
  `collected` int DEFAULT '0' COMMENT '我们库里这个知识点**及其全部子孙**累计有多少道题（站点给题打的标签是最细那一层，父节点一道都不标，只数本节点会永远是 0）。★必须用 knowledge_recount() 重算，不能每采一道 +1 —— 采集是可以重跑的，累加会一直膨胀',
  `last_page` int DEFAULT '0' COMMENT '上次采到第几页。顺序翻页模式下断点续采靠它，下次从 last_page+1 开始；随机分块模式下改看 covered_pages，这一列只当''曾经到过的最大页码''参考',
  `scraped_at` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '上次采集时刻',
  `note` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '人话备注，比如撞硬顶时记下还差多少题',
  `covered_pages` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '随机分块翻页模式下，这个知识点已经采过的页码区间，如 1-40,88-120,300-410。断点续采从缺口里随机挑一段，见 store.pick_page_chunk()',
  PRIMARY KEY (`knowledge_id`) USING BTREE,
  KEY `idx_kt_parent` (`parent_id`) USING BTREE,
  KEY `idx_kt_level` (`level`) USING BTREE,
  KEY `idx_kt_todo` (`is_leaf`,`scrape_status`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='知识点树快照。★不分年级也不分教材版本，一棵管到底；来自免费静态 JSON，不用浏览器';

CREATE TABLE `knowledge_slice` (
  `knowledge_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '知识点 ID，带 zsd 前缀',
  `slice_key` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '切片标识，各维度码首尾相接，和 URL 里的段一模一样：t1=单选题，t1d2=单选题+适中。既是主键也能直接拼 URL',
  `dim` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '这一片是按哪个维度切出来的：qtype 题型 / difficulty 难度',
  `slice_name` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '人话名字，如「单选题」「单选题·适中」',
  `depth` int DEFAULT '1' COMMENT '切了几层。1=只切了题型，2=题型+难度',
  `scrape_status` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'none' COMMENT '这一片的采集状态：none / partial / slicing 这一片还超硬顶已再往下切 / done / capped 切到底还是超 / empty 这一片没题',
  `site_total` int DEFAULT NULL COMMENT '站点说这一片有多少道题（带筛选条件的列表页 #questioncount）',
  `collected` int DEFAULT '0' COMMENT '库里这一片有多少道题。★用 knowledge_slice_recount() 重算，不能累加',
  `last_page` int DEFAULT '0' COMMENT '这一片上次采到第几页，断点续采靠它（随机分块模式下改看 covered_pages，这一列只当''曾经到过的最大页码''参考）',
  `note` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '人话备注',
  `scraped_at` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '上次采集时刻',
  `covered_pages` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '随机分块翻页模式下，这一片已经采过的页码区间，如 1-40,88-120。断点续采从缺口里随机挑一段，见 store.pick_page_chunk()',
  PRIMARY KEY (`knowledge_id`,`slice_key`) USING BTREE,
  KEY `idx_ks_todo` (`knowledge_id`,`scrape_status`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='知识点切片进度。★题多到翻页翻不完（硬顶 999 页 = 9990 道）的知识点，按题型/难度切开分片采，一片一行';
