# CodeMind MCP 面试准备

---

## 一、30 秒电梯演讲（必须背熟）

> "我做了一个让 Claude 能读懂本地私有代码库的工具。用 Claude 看私有代码时，Claude 看不到代码——现有的 Copilot、Cursor 又要把代码传云端，企业不允许。我的工具全部本地运行，代码不出网，用 BM25 + 语义向量混合检索 + 重排序 + 意图感知路由，在 FastAPI 真实语料上 R@5 从 0.30 提升到了 0.60（+100%）。"

---

## 二、简历内容

**项目介绍**

面向隐私敏感场景的本地代码语义检索工具，通过 MCP 协议为 Claude Desktop 提供私有代码库导航能力。采用 BM25 + BGE-M3 密集向量混合检索 + 交叉编码器重排序三阶段管线，全流程本地运行，代码不出网，无需任何外部 API。支持 Python / TypeScript / Java / Go 四语言 AST 感知分块，提供语义搜索、函数定位、引用查找等 5 个 MCP 工具。

**技术栈**：Python / tree-sitter / BGE-M3 / Qdrant / BM25 / Cross-Encoder Reranker / MCP Protocol / SQLAlchemy / Docker

**核心职责**：
- 独立设计并实现基于 MCP 协议的本地代码语义检索服务器，解决开发者使用 Claude 辅助私有代码库导航时代码不能出网的痛点，全程无外部 API 依赖
- 基于 tree-sitter 实现四语言（Python / TypeScript / Java / Go）AST 感知代码分块，保留函数 / 类 / 方法语义边界，避免固定窗口切割上下文
- 构建三阶段混合检索管线：BM25 稀疏检索 + BGE-M3 本地密集向量 + RRF 融合 + BGE-reranker-v2-m3 交叉编码器重排序
- 实现 5 个 MCP 工具（语义搜索、函数定位、引用查找、文件列举、Git Blame），符合 MCP stdio JSON-RPC 协议规范，支持接入 Claude Desktop
- 构建 50 题评测集（FastAPI 1119 文件 / 7182 个 AST chunk 真实语料），按 locate / understand / compare 三类意图以 Recall@K + MRR 量化评估，通过消融实验逐组件量化各路径贡献

**成果**：
- 检索召回率：BM25-only R@5 = 0.30 → Hybrid+Rerank+IntentRouting R@5 = 0.60（相对提升 +100%）
- 通过 eval 数据驱动发现并修复 source boost 逻辑缺陷，修复后 compare 类 R@3 从 0.30 提升至 0.50（+67%）
- 0 mypy 错误，40/40 单元测试通过，支持 Docker 一键部署
- GitHub：github.com/Sanyuewu/codemind-mcp

---

## 三、关键数字速查

| 指标 | 数值 |
|------|------|
| eval 题目数 | 50 题（locate×20, understand×20, compare×10） |
| 测试语料 | FastAPI 1119 文件，7182 个 AST chunk |
| BM25-only R@5 | 0.30 |
| Dense-only R@5 | 0.40（locate=0.15, understand=0.55, compare=0.60） |
| Hybrid R@5 | 0.46 |
| Hybrid+Rerank top_k=10 R@5 | 0.56（locate=0.45, understand=0.60, compare=0.70） |
| Hybrid+Rerank top_k=50 R@5 | 0.52（locate=0.55↑, understand=0.55↓, compare=0.40↓） |
| **Hybrid+Rerank intent-aware R@5** | **0.60**（locate=0.55, understand=0.60, compare=0.70）|
| compare R@3（boost 前/后） | 0.30 → 0.50（+67%） |
| 代码质量 | 0 mypy errors，40/40 tests，Docker 支持 |
| 开发周期 | 14 天，27 commits |

**完整优化路径**：BM25-only 0.30 → Hybrid 0.46 → +Rerank 0.56 → +Intent-Routing **0.60**（+100% vs 起点）

**消融实验关键结论**：top_k=50 非单调提升（locate +0.10，compare −0.30），揭示了精确匹配与语义查询的根本性 trade-off。意图感知路由通过查询分类消除了这一矛盾，同时保持两类查询的最优表现。

---

## 四、每个技术的深度问答

### 4.1 BM25

**Q: BM25 和 TF-IDF 的区别？**

BM25 核心公式：
```
score(D,Q) = Σ IDF(qi) × f(qi,D)×(k1+1) / (f(qi,D) + k1×(1 - b + b×|D|/avgdl))
```

两个关键改进：
1. **词频饱和**：TF-IDF 里词频线性增长，BM25 有上限（k1 控制，通常 1.2）——一个词出现 100 次不应该比出现 10 次好 10 倍
2. **文档长度归一化**：b 参数（通常 0.75）惩罚长文档，代码文件长短差异大，这点很重要

**Q: BM25 数据存在哪里？**

SQLite FTS5 全文索引（metadata.db）。chunk 写入时同步建 FTS5 索引，BM25 检索通过 `MATCH` 查询返回候选，再传入 RRF 融合。

**Q: BM25 在代码搜索什么场景好？**

函数名、类名是精确关键词，locate 类查询（"jsonable_encoder 在哪"）BM25 直接命中；understand 类（"如何做依赖注入"）BM25 完全不行，需要语义向量。

---

### 4.2 BGE-M3

**Q: 为什么选 BGE-M3 而不是 OpenAI embedding？**

私有代码不能发 API——这是整个工具的核心价值主张。发 OpenAI API 等于把代码给第三方，从根本上破坏隐私保证。代价是 CPU 推理慢（约 1 chunk/s），索引 7000 个 chunk 需要约 2 小时。

**Q: Bi-encoder vs Cross-encoder？**

| | Bi-encoder（BGE-M3） | Cross-encoder（Reranker） |
|--|--|--|
| 编码方式 | query 和 doc 分别编码 | [query, doc] 拼接联合编码 |
| 能否预计算 | ✅ doc 向量预存 | ❌ 每次重新推理 |
| 精度 | 中等 | 高 |
| 适用场景 | 初检（面对全量） | 精排（面对 top-20） |

---

### 4.3 RRF（Reciprocal Rank Fusion）

**Q: 公式和 k=60 的来源？**

`RRF(d) = Σ 1 / (k + r(d))`，k=60 是 2009 年 Cormack 等论文的经验值，在多个 IR 数据集上稳健。k 越大排名差距越平滑，防止一路结果完全压制另一路。

**Q: 为什么不用加权平均？**

BM25 分数是词频统计（数值可以很大），Dense 是余弦相似度（-1 到 1），量纲完全不同。直接加权需要归一化 + 人工调权重，RRF 只看排名，无需调参，稳健。

---

### 4.4 Cross-Encoder Reranker

**Q: Reranker 为什么只用于精排而不做初检？**

7182 个 chunk 每次都过 cross-encoder，CPU 上要几分钟，不可用。只对 top-20 候选操作，每次约 1-2 秒。

**Q: max_length=512 有什么影响？**

代码超过 512 token 被截断。APIRouter 类 4000 行，截断后语义信息严重丢失，这是 locate 类 R@5 只有 0.45 的根因之一。

---

### 4.5 tree-sitter

**Q: AST 分块 vs 固定窗口的 trade-off？**

- **固定窗口**：简单，但会把函数切断，chunk 语义破碎
- **AST**：保留完整函数/类边界，但 chunk 大小不均匀——小函数 5 行，大类 4000 行，大 chunk 嵌入质量差

**Q: chunk_id 为什么用起始行而不是内容 hash？**

`sha256(file_path + ':' + str(start_line))[:16]`。用内容 hash 的话，文件改动后旧 chunk 无法按位置定位删除，增量更新无法实现。

---

### 4.6 Qdrant

**Q: 索引结构？**

HNSW（Hierarchical Navigable Small World），分层图，ANN 搜索 O(log N)。

**Q: embedded mode 的局限？**

单进程单用户，不支持多客户端并发。如果需要多人团队共用：切 Qdrant server mode + payload filter 做权限隔离。

---

### 4.7 MCP 协议

**Q: Claude 怎么调用工具？**

MCP 通过 stdio JSON-RPC 2.0 通信。Claude Desktop 把 MCP server 作为子进程启动，发 JSON 消息，server 执行工具逻辑返回结果。工具三要素：`name`、`description`（Claude 根据这个决定何时调用）、`inputSchema`。

Claude Desktop 配置：
```json
{
  "mcpServers": {
    "codemind": {
      "command": "uv",
      "args": ["run", "codemind-mcp"],
      "env": {"CODEMIND_DATA_DIR": "/path/to/.codemind"}
    }
  }
}
```

**Q: 5 个工具各自解决什么问题？**

1. `search_code`：语义搜索，最常用
2. `get_function`：按名字精确定位，不走向量检索，locate 类快捷路径
3. `find_references`：符号引用查找，依赖分析
4. `list_files`：项目结构浏览
5. `git_blame`：提交历史查询

---

## 五、最重要的 Bug（STAR，必须背熟）

**S**：加了 source boost，给 library source 文件分数乘 1.5×，想压制 tutorial 文件

**T**：跑 eval 验证效果

**A**：factor=1.0 和 factor=1.5 跑出来结果完全一样，50 道题 pass/fail 逐条一致。说明 boost 没生效。追溯代码发现：boost 修改了 `score_map`（一个 dict），但 `reranker.rerank(query, chunks)` 只接受 `list[CodeChunk]`，根本不读 `score_map`，等于空操作。把 boost 移到 reranker 输出之后，直接乘以 `RetrievedChunk.score`，重新排序。

**R**：compare 类 R@3 从 0.30 → 0.50（+67%）。亮点：用 eval 发现问题 → 追溯根因 → 修复 → eval 验证，完整数据驱动闭环。

---

## 六、已知弱点主动防守

| 弱点 | 防守答案 |
|------|---------|
| locate R@5=0.45 最差 | 根因：FastAPI 72% 是 docs/tests，且 APIRouter 4000 行被 cross-encoder 截断；下一步对大类二次分块 |
| eval 只有 50 题 | 三类意图平衡、真实语料、足以发现系统性问题；生产级应扩展到 500 题 |
| 覆盖率 39% | 核心逻辑 70%+，基础设施层（Qdrant+embedding）选择不 mock，mock 掩盖真实集成问题 |

---

## 七、系统设计追问

**"100 万文件怎么办"**

瓶颈逐层：CPU embedding 完全不行（1 chunk/s × 1000 万 chunk = 116 天）→ GPU 推理或 OpenAI API（权衡隐私）；Qdrant embedded → server mode；SQLite FTS5 → Elasticsearch

**"100 人团队共用一个索引"**

Qdrant server mode；payload filter 按 repo/team 隔离；git post-receive hook 触发增量更新；chunk_id 加 repo 命名空间前缀

**"如何实时更新索引"**

现有增量接口（sha256 比对）+ `watchfiles` 后台监听文件变更，触发 `indexer.update_file()`，与 MCP server 共用同一个 asyncio event loop

---

## 八、代码手写题准备

**RRF 融合**
```python
def rrf(*rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, (doc_id, _) in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

**async 并发检索**
```python
bm25_task = asyncio.create_task(asyncio.to_thread(bm25.search, query, k))
dense_task = asyncio.create_task(dense.search(query, k))
bm25_res, dense_res = await asyncio.gather(bm25_task, dense_task)
```

**BM25 IDF**
```python
import math
def idf(n_docs: int, doc_freq: int) -> float:
    return math.log((n_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1)
```

---

## 九、不同岗位的侧重点

- **AI 工程**：三阶段管线 + eval + 消融实验，体现"真正理解每个组件的 why"
- **后端 Python**：SQLAlchemy / Pydantic / asyncio / Docker，eval 作为工程质量佐证
- **DevTools**：MCP 协议 + 5 个工具设计决策 + .codemindignore 隐私考量

---

## 十、投实习的策略

**优先投**：AI 创业公司（对项目质量敏感，对学历/实习经历宽松）；独角兽 AI infra / 工具团队

**不建议第一批投**：大厂提前批（字节/腾讯/阿里，HR 筛选标准僵化）；纯算法岗（项目不展示模型训练背景）

**核心判断**：项目本身不是瓶颈，简历的其他部分（实习经历、基础课、项目广度）才决定天花板
