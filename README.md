# Planning PDF Knowledge Base

一个面向“规划类 PDF 文件”的 GitHub 本地知识库管理系统。它不是简单的文件归档，而是一个围绕文档解析、元数据治理、分段索引、静态检索展示和后续知识增强而设计的工程化仓库。

## 1. 系统设计方案

### 1.1 总体目标

本项目用于把本地的规划类 PDF 文档沉淀为一个可长期维护的 GitHub 知识库，覆盖以下能力：

- 统一存储 PDF 原件、解析结果、结构化索引与展示页面
- 支持从本地目录批量导入 PDF
- 自动抽取文档级 metadata、章节与段落级 chunk
- 生成适合 GitHub Pages 的静态 JSON 检索数据
- 支持标题、全文、地区、年份、规划类型、规划层级、标签筛选
- 为 OCR、BM25、向量检索、知识图谱、RAG/LLM 问答预留扩展位

### 1.2 为什么这样设计

规划类文档和普通 PDF 管理的核心区别在于：

- 它们天然带有行政区、年份、规划层级、规划类型等治理属性
- 同一地区常常存在多期版本，需要串联版本谱系
- 文档结构复杂，常见“第一章/第二章”“一、二、三”“附录”“图件说明”
- 页眉页脚、附件说明、表格碎片会污染原始文本
- 后续常常会被用于政策对比、术语抽取、专题梳理、问答与知识图谱

因此本项目采用“原件层 + 解析层 + 索引层 + 展示层”的分层结构，避免把 GitHub 仓库做成简单文件夹堆放。

### 1.3 系统架构

```text
本地 PDF 目录
  -> scripts/import_pdfs.py
  -> raw_pdfs/            # 原件入库
  -> parsed/documents/    # 文档级解析结果
  -> parsed/chunks/       # 段落/章节级结果
  -> data/                # 聚合索引、筛选面板、统计数据
  -> site/                # GitHub Pages 静态站点
  -> .github/workflows/   # 自动化构建与发布
```

模块划分：

- `导入模块`：扫描本地目录、复制 PDF、解析文件名、生成文档 ID
- `解析模块`：提取文本、清洗噪声、识别章节、切分 chunk、生成 metadata
- `索引模块`：聚合所有文档和 chunk，输出静态 JSON 索引
- `展示模块`：用原生 HTML/CSS/JS 加载 JSON，提供搜索和筛选
- `自动化模块`：用 GitHub Actions 在 push 后重新构建索引和站点

### 1.4 核心模块设计

#### A. 文档导入模块

职责：

- 扫描指定目录下所有 PDF
- 基于文件名与路径规则推断地区、年份、文种
- 为每个文件生成稳定 `doc_id`
- 复制原始 PDF 到仓库 `raw_pdfs/`
- 调用解析流程写入 `parsed/` 和 `data/`

为什么这样设计：

- 本地批量导入是主入口，适合真实工作流
- `doc_id` 稳定后，后续版本串联、增量更新、引用关系都会更稳定

#### B. 文档解析模块

MVP 处理：

- 用 `pypdf` 提取可复制文本 PDF
- 提取页数、文本长度、文件 hash
- 基于正则清理空白、页眉页脚重复文本
- 基于章节模式切分 chunk
- 提取关键词、生成摘要占位

增强版处理：

- OCR 扫描件识别
- 表格区域检测与附录识别
- 页眉页脚跨页频次统计去噪
- 行政区词典、规划词典辅助打标签

#### C. 索引与知识管理模块

文档级：

- metadata 治理
- 标签体系
- 分类体系
- 版本链条
- 相关文档关联

chunk 级：

- 支持段落全文检索
- 支持章节定位
- 为向量化与 RAG 预留最小语义单元

#### D. 前端展示模块

MVP 页面：

- 首页：系统简介、统计卡片、筛选入口
- 文档列表：搜索 + 多条件筛选
- 文档详情：metadata、摘要、章节片段、相关文档

为什么采用静态站点：

- GitHub Pages 部署简单
- 数据直接读取 JSON，低成本、易维护
- 后续可以无缝替换为更复杂前端，但不会推翻数据层

### 1.5 核心数据流

1. 用户执行本地导入命令，扫描一个或多个 PDF 目录
2. PDF 被复制到 `raw_pdfs/`，并生成稳定文件 hash
3. 解析器抽取文本并输出单文档 JSON
4. 清洗器去除页眉页脚、规范空白、切章节和 chunk
5. 元数据生成器输出文档级 metadata
6. 索引器汇总为 `documents.json`、`chunks.json`、`facets.json`
7. 前端页面从 `data/` 加载静态 JSON 实现检索与展示
8. GitHub Actions 在数据更新后自动重建索引并发布 Pages

### 1.6 与普通文件管理的区别

普通文件管理关注“文件是否能找到”；本系统关注“知识是否可组织、可检索、可关联、可扩展”。差异体现在：

- 不是只存 PDF，而是同时存 metadata、chunk、索引和关系
- 不是按文件夹死板归档，而是支持多维筛选
- 不是一次性处理，而是支持版本追踪和增量重建
- 不是只能人工阅读，而是为术语、图谱、RAG、问答留好结构化接口

### 1.7 如何兼顾 GitHub 托管与后续扩展

MVP 把所有关键数据都保持为纯文本工件：

- PDF 原件：`raw_pdfs/`
- 单文档解析 JSON：`parsed/documents/`
- 单文档 chunk JSON：`parsed/chunks/`
- 聚合索引：`data/`
- 展示页面：`site/`

这样既适合 Git 版本控制，也便于后续接入：

- BM25：直接基于 `chunks.json`
- 向量检索：新增 `data/embeddings/` 或外部向量库同步脚本
- 知识图谱：新增 `graph/entities.json`、`graph/relations.json`
- LLM/RAG：直接读取 chunk 与 metadata

## 2. 推荐目录结构

```text
.
├─ .github/
│  └─ workflows/
├─ config/
│  └─ config.yaml
├─ data/
│  ├─ documents.json
│  ├─ chunks.json
│  ├─ facets.json
│  └─ stats.json
├─ docs/
│  └─ architecture.md
├─ parsed/
│  ├─ documents/
│  └─ chunks/
├─ raw_pdfs/
│  └─ incoming/
├─ scripts/
│  ├─ import_pdfs.py
│  ├─ parse_pdf.py
│  └─ build_index.py
├─ site/
│  ├─ index.html
│  └─ app.js
├─ requirements.txt
└─ README.md
```

目录说明：

- `raw_pdfs/`：仓库内保存原始 PDF，适合作为事实来源与版本归档
- `parsed/documents/`：每个 PDF 对应一个文档级解析结果
- `parsed/chunks/`：每个 PDF 对应一个 chunk 列表文件
- `data/`：前端直接消费的聚合索引
- `site/`：GitHub Pages 静态页面
- `scripts/`：本地导入、解析、建索引脚本
- `config/`：规则、路径、停用词、模式配置
- `docs/`：补充架构、数据规范、术语设计文档

## 3. Metadata Schema 设计

### 3.1 文档级 metadata

```json
{
  "id": "cn-guangdong-shenzhen-master-plan-2018-v1",
  "title": "深圳市国土空间总体规划（2018-2035年）",
  "aliases": ["深圳市总体规划2018版"],
  "region": "深圳市",
  "province": "广东省",
  "city": "深圳市",
  "county": null,
  "admin_level": "city",
  "year": 2018,
  "year_range": "2018-2035",
  "plan_level": "总体规划",
  "plan_type": "国土空间规划",
  "document_type": "规划文本",
  "status": "active",
  "version": "v1",
  "version_group": "shenzhen-master-plan",
  "source_filename": "深圳市国土空间总体规划（2018-2035年）.pdf",
  "source_path": "raw_pdfs/incoming/深圳市国土空间总体规划（2018-2035年）.pdf",
  "file_hash": "sha256:...",
  "page_count": 326,
  "text_length": 582431,
  "language": "zh-CN",
  "keywords": ["生态保护红线", "城镇开发边界", "空间分区"],
  "tags": ["广东", "深圳", "国土空间", "总体规划"],
  "categories": ["区域规划", "空间治理"],
  "summary": "文档摘要或后续 LLM 生成摘要。",
  "related_docs": ["cn-guangdong-shenzhen-eco-plan-2020-v1"],
  "previous_version_id": null,
  "next_version_id": null,
  "has_ocr": false,
  "parser": {
    "engine": "pypdf",
    "ocr_engine": null,
    "parsed_at": "2026-04-09T19:30:00+08:00"
  },
  "quality": {
    "text_extractable": true,
    "header_footer_cleaned": true,
    "chapter_detected": true,
    "table_text_noise": "medium"
  },
  "extensions": {
    "graph_entity_ids": [],
    "timeline_topic_ids": [],
    "rag_ready": true
  },
  "created_at": "2026-04-09T19:30:00+08:00",
  "updated_at": "2026-04-09T19:30:00+08:00"
}
```

### 3.2 Chunk 结构

```json
{
  "id": "cn-guangdong-shenzhen-master-plan-2018-v1-c0001",
  "doc_id": "cn-guangdong-shenzhen-master-plan-2018-v1",
  "chunk_index": 1,
  "chapter_path": ["第一章 总则", "一、规划范围"],
  "heading": "一、规划范围",
  "page_start": 3,
  "page_end": 4,
  "text": "规划范围包括......",
  "text_length": 368,
  "keywords": ["规划范围", "管理边界"],
  "tags": ["章节正文"],
  "chunk_type": "paragraph",
  "is_appendix": false,
  "is_table_like": false
}
```

### 3.3 聚合索引结构

`data/documents.json`

- 前端文档主列表
- 每条记录保留检索和展示核心字段

`data/chunks.json`

- 前端全文检索基础
- 后续 BM25/RAG 的统一输入

`data/facets.json`

- 各筛选维度枚举，如地区、年份、规划类型、层级、标签

`data/stats.json`

- 知识库统计信息，如文档数、chunk 数、地区数、最近更新时间

### 3.4 标签与分类建议

固定维度：

- `admin_level`：province / city / county / town
- `plan_type`：国土空间规划 / 生态保护规划 / 总体规划 / 专项规划 / 实施方案 / 技术指南 / 评估报告 / 政策文件 / 会议纪要 / 标准规范
- `plan_level`：总体规划 / 专项规划 / 详细规划 / 实施方案 / 指南规范

推荐标签：

- 地区标签：广东、深圳、福田
- 主题标签：生态红线、永久基本农田、城镇开发边界、国土整治、用途管制
- 状态标签：现行、废止、草案、送审稿
- 结构标签：附录、图则、评估、监测

## 4. 文档处理流程设计

### 4.1 MVP 基础版

1. 扫描文件
2. 提取基础信息
3. 提取文本
4. 清洗文本
5. 去除页眉页脚
6. 章节识别
7. chunk 切分
8. 关键词提取
9. 标签生成
10. metadata 生成
11. 检索索引生成
12. 写入 GitHub 仓库

### 4.2 增强版

- OCR：接入 `ocrmypdf` 或 `paddleocr`
- 页眉页脚去噪：做跨页频率统计和位置权重
- 表格识别：标记表格块和附录块
- 摘要生成：接入 LLM 批处理
- 文档关联：基于同地区、同主题、同版本组自动推荐

### 4.3 产品级扩展版

- 向量检索与 RAG
- 规划术语表与知识卡片
- 政策演化时间轴
- 地区专题页和主题专题页
- 知识图谱实体关系抽取
- 多来源同步与增量任务编排

## 5. MVP 运行方式

- Python 3.11
- `pip install -r requirements.txt`
- `python scripts/import_pdfs.py --input-dir "D:\planning_pdfs" --config config/config.yaml`
- `python -m http.server 8000`
- 访问 `http://localhost:8000/site/`

## 6. GitHub Actions 自动化方案

MVP 工作流：

- 在 `scripts/`、`config/`、`parsed/`、`data/`、`site/` 更新时触发
- 自动安装依赖
- 重新构建 `data/*.json`
- 发布 `site/` 和 `data/` 到 GitHub Pages

说明：

- Actions 无法直接访问你本地未提交的 PDF
- 本地导入是主流程，GitHub Actions 负责“重建与发布”
- 如果未来把 PDF 直接 push 到仓库，也可以触发自动解析

## 7. 前端展示方案

MVP 页面包括：

- 首页统计卡片：文档数、chunk 数、地区数、最近更新时间
- 搜索框：标题 / 全文关键词
- 筛选器：地区、年份、规划类型、规划层级、标签
- 文档卡片：标题、年份、地区、标签、摘要
- 详情面板：metadata、章节片段、相关文档

## 8. 后续扩展路线

### MVP

- 本地导入
- PDF 文本抽取
- metadata 与 chunk 输出
- 静态全文检索与筛选页面

### 增强版

- OCR 扫描件支持
- 更强的章节识别
- 自动摘要
- 自动关联推荐

### 产品级扩展版

- BM25 与向量双检索
- LLM 问答
- 知识图谱
- 术语表、知识卡片、政策演化时间轴
- 专题聚类页和地区专题页

## 9. 下一步迭代建议

1. 先拿 20 到 50 份真实规划 PDF 跑一遍，校验文件名规则和章节识别命中率
2. 建一份 `region_aliases.csv` 和 `planning_terms.txt`，提升 metadata 与标签质量
3. 对扫描版样本评估 OCR 路线，优先决定 `ocrmypdf` 还是 `paddleocr`
4. 为版本串联单独建立 `version_group` 规则，解决同一区域多期规划跟踪
5. 在 `data/` 增加 `relations.json`，开始沉淀跨文档引用与主题关联

---

本仓库当前已经提供一个最小可运行骨架，适合作为 GitHub 项目的起点，并为后续扩展保留了清晰边界。
