---
name: worldquant-brain-interactive
description: 交互式 WorldQuant BRAIN Alpha 研究工作流。Use for BRAIN 登录、字段查询、alpha 生成模拟、提交检查、表达式验证和运行排障。
---

# WorldQuant BRAIN 交互式 Alpha 研究工作流

本 skill 是自包含的「工作流说明书 + 环境检查工具 + API 参考」。不要读取其他说明文件来理解本 skill；下文已经内联运行规则、默认参数、API 约定、表达式模板、断点文件和常见问题。

实际执行时优先使用当前工作区内的 Python 文件；若用户指定了其他项目根，才切换到该目录运行。不要硬编码旧源路径。

## 总原则

- 全程使用用户所用语言交流。
- 真实执行前先做环境检查；凭据、依赖、路径问题必须先暴露。
- 不打印密码、token、cookie、完整 `.env` 内容或认证 header。
- 网络请求必须考虑限流和长轮询；不要裸写无限轮询。
- 数字必须来自真实输出；排序、合计和统计用工具计算。
- 多个 alpha 对比时用表格展示表达式、alpha ID、Sharpe、Fitness、Turnover、Correlation、状态。
- 结果不满意时优先调整阈值、settings、数据集、字段筛选或断点策略后重跑。

## 环境约定

默认在当前工作区执行。若用户提供项目根，用用户提供路径；否则按以下顺序定位：

1. 当前工作目录。
2. 环境变量 `WQB_PROJECT_ROOT`。
3. 向用户询问项目根路径。

一个可执行项目根通常包含：

- `machine_lib.py`
- `alpha_machine.py`
- `alpha_explorer.py`
- `validate_operator_wqbkit.py`
- `config.py`
- `.env`

依赖清单：`requests>=2.32,<3`、`pandas>=2.2,<4`、`ipykernel>=6,<8`、`notebook>=7,<8`、`pytest>=8,<10`、`python-dotenv>=1,<2`、`wqbkit==0.4.7`、`psycopg[binary]>=3,<4`。

`.env` 凭据规则来自 `config.py`：

- `load_project_env()` 只读取项目根同级 `.env`，并覆盖当前进程环境。
- `load_wqb_credentials()` 要求 `WQB_USERNAME` 和 `WQB_PASSWORD` 必须存在且非空。
- 工作流 C 还要求 `DB_ENABLE=true` 或 `1` 或 `yes`，并需要数据库相关 `DB_*` 配置可用。

## 内联环境检查

每次运行工作流前，执行下面的自包含检查命令。不要依赖外部 `check_env.py`。

```bash
PROJECT_ROOT="${WQB_PROJECT_ROOT:-$PWD}"
cd "$PROJECT_ROOT" && python3 - <<'PY'
from pathlib import Path
import importlib.util
import os
import sys

root = Path.cwd()
required_files = [
    "machine_lib.py",
    "alpha_machine.py",
    "alpha_explorer.py",
    "validate_operator_wqbkit.py",
    "config.py",
]
missing_files = [name for name in required_files if not (root / name).exists()]
env_path = root / ".env"

def read_env(path):
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values

env = read_env(env_path)
missing_creds = [
    key for key in ("WQB_USERNAME", "WQB_PASSWORD")
    if not env.get(key) and not os.environ.get(key)
]
modules = ["requests", "pandas", "dotenv"]
missing_modules = [m for m in modules if importlib.util.find_spec(m) is None]
wqbkit_available = importlib.util.find_spec("wqbkit") is not None
db_enabled = (env.get("DB_ENABLE") or os.environ.get("DB_ENABLE") or "").lower() in {"true", "1", "yes"}

print(f"project_root={root}")
print(f"env_file={'present' if env_path.exists() else 'missing'}")
print("credentials=" + ("present" if not missing_creds else "missing:" + ",".join(missing_creds)))
print("core_files=" + ("present" if not missing_files else "missing:" + ",".join(missing_files)))
print("python_modules=" + ("present" if not missing_modules else "missing:" + ",".join(missing_modules)))
print(f"wqbkit={'present' if wqbkit_available else 'missing'}")
print(f"db_enabled={db_enabled}")

if missing_files or missing_creds or missing_modules:
    sys.exit(1)
if not wqbkit_available or not db_enabled:
    sys.exit(2)
PY
```

解释检查结果：

- exit `0`：核心文件、凭据、基础依赖、wqbkit、DB 开关都可用。
- exit `1`：核心运行阻塞，先修复缺失文件、`.env` 凭据或基础依赖。
- exit `2`：A/B 工作流可继续；C 工作流不可用，除非安装 `wqbkit==0.4.7` 并配置 DB。

解释阻塞时只报告缺失项，不展示任何敏感值。

## Python 解释器选择

运行脚本时优先使用项目 `.venv`：

```bash
PYTHON_BIN=".venv/bin/python"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="python3"
PYTHONUNBUFFERED=1 "$PYTHON_BIN" -u <script.py> <args>
```

后台长任务必须使用 `PYTHONUNBUFFERED=1` 和 `-u`，方便实时读取进度。

## 工作流 A：完整 Alpha Machine 流水线

适用场景：用户要跑完整 alpha 生成、筛选、二阶分组、trade_when、提交检查或模板表达式流水线。

8 个阶段：

1. 拉主数据集字段。
2. 一阶 alpha 生成并模拟。
3. 一阶 alpha 按已有 alpha 查询结果筛选。
4. 二阶分组 alpha 生成并模拟。
5. 二阶 alpha 筛选。
6. 三阶 `trade_when` alpha 生成并模拟。
7. 提交候选检查 `check_submission`。
8. sentiment × option 模板表达式构建。

默认配置来自 `WorkflowConfig`：

| 参数 | 默认值 |
|---|---|
| `--dataset-id` | `analyst4` |
| `--field-prefix` | `anl4` |
| `--region` | `USA` |
| `--universe` | `TOP3000` |
| `--delay` | `1` |
| `--neutralization` | `SUBINDUSTRY` |
| `--initial-decay` | `6` |
| `--simulations-per-batch` | `3` |
| `--start-date` | `02-27` |
| `--end-date` | `02-28` |
| `--prune-keep` | `5` |
| `--first-sharpe` / `--first-fitness` / `--first-alpha-limit` | `1.0` / `0.7` / `100` |
| `--second-sharpe` / `--second-fitness` / `--second-alpha-limit` | `1.3` / `0.8` / `200` |
| `--submit-sharpe` / `--submit-fitness` / `--submit-alpha-limit` | `1.25` / `1.0` / `200` |
| `--first-simulation-start` | `0` |
| `--second-simulation-start` | `0` |
| `--third-simulation-start` | `3` |
| `--option-dataset-id` | `option8` |
| `--sentiment-dataset-id` | `sentiment1` |
| `--seed` | unset |
| `--fresh` | false |

执行模板：

```bash
cd "$PROJECT_ROOT"
PYTHON_BIN=".venv/bin/python"; [ -x "$PYTHON_BIN" ] || PYTHON_BIN="python3"
PYTHONUNBUFFERED=1 "$PYTHON_BIN" -u alpha_machine.py \
  --dataset-id analyst4 \
  --field-prefix anl4 \
  --region USA \
  --universe TOP3000 \
  --neutralization SUBINDUSTRY \
  --initial-decay 6 \
  --simulations-per-batch 3
```

断点：

- 文件：`alpha_machine_checkpoint.json`。
- 默认断点续跑；中断后重跑同命令即可。
- 用户明确要求重新开始时加 `--fresh`。
- 不要擅自删除断点文件。

结果展示：

- 解析末尾 `Workflow complete:`。
- 展示 `data_field_count`、`first_order_count`、`second_order_count`、`third_order_count`、`submittable_count`、`template_count`。
- 若有失败批次，列出失败 alpha/阶段/错误，并建议续跑或降低并发。

## 工作流 B：表达式探索

适用场景：用户要从某个数据集字段自动生成表达式，并搜索 settings。

默认配置来自 `alpha_explorer.py`：

- `DATASET_ID = "pv13"`
- `DATA_TYPE = "MATRIX"`
- `MIN_SHARPE = 1.25`
- `MIN_FITNESS = 1.0`
- `PROGRESS_FILE = "alpha_progress_fine.pkl"`
- `MAX_SETTINGS_PER_EXPR = 5`
- `SIMULATIONS_PER_BATCH = 3`

快速预筛选 settings：

```json
{
  "instrumentType": "EQUITY",
  "region": "USA",
  "universe": "TOP3000",
  "delay": 1,
  "decay": 0,
  "neutralization": "MARKET",
  "truncation": 0.08,
  "pasteurization": "ON",
  "unitHandling": "VERIFY",
  "nanHandling": "ON",
  "language": "FASTEXPR",
  "visualization": false
}
```

settings 搜索空间：

- `delay`: `[1]`
- `decay`: `[0, 3, 7]`
- `neutralization`: `["MARKET", "SECTOR", "INDUSTRY"]`
- `truncation`: `[0.05, 0.08, 0.1]`
- `pasteurization`: `["ON", "OFF"]`
- `nanHandling`: `["ON", "OFF"]`
- 每个表达式随机抽样，默认最多测试 5 组 settings。

字段分类与模板：

- price/return 字段：`reverse(ts_delta(field, 5))`、`ts_mean(field, 5) / ts_mean(field, 63)`、`ts_std_dev(field, 20)`、`ts_rank(field, 252)`、`ts_av_diff(field, 20)`、`signed_power(ts_av_diff(field, 20), 1.5)`、`ts_arg_max(field, 63)`。
- volume 字段：`ts_corr(field, close, 20)`、`multiply(ts_delta(field, 10), ts_delta(close, 10))`、`and(ts_delta(field, 10) > 0, ts_delta(close, 10) > 0)`。
- fundamental 字段：`ts_rank(field, 252)`、`ts_zscore(field, 252)`、`ts_decay_linear(field, 126)`、`divide(field, close)`。
- 所有字段通用：`rank(field)`、`zscore(field)`、`ts_zscore(field, 63)`、`ts_delta(field, 20)`、`ts_sum(field, 20)`、`ts_delay(field, 1)`。

执行模板：

```bash
cd "$PROJECT_ROOT"
PYTHON_BIN=".venv/bin/python"; [ -x "$PYTHON_BIN" ] || PYTHON_BIN="python3"
PYTHONUNBUFFERED=1 "$PYTHON_BIN" -u alpha_explorer.py
```

断点：

- 文件：`alpha_progress_fine.pkl`。
- 默认自动续跑。
- 若用户要重跑，先确认是否删除该 pickle 文件。

结果展示：

- 解析 `===== 探索完成 =====` 后的统计。
- 展示总运行表达式数、优质 Alpha 数、跳过字段数。
- 对每个优质 alpha 展示 `ID`、`Sharpe`、`Fitness`、最优 settings。

## 工作流 C：批量验证 FASTEXPR

适用场景：用户给出一个或多个 FASTEXPR，要求提交模拟并按指标验证。

依赖：

- `wqbkit==0.4.7`
- `DB_ENABLE=true` 或 `1` 或 `yes`
- `.env` 中存在 `WQB_USERNAME`、`WQB_PASSWORD` 和数据库配置。

默认验证阈值来自 `ValidationConfig`：

| 参数 | 默认值 |
|---|---|
| `--region` | `USA` |
| `--universe` | `TOP3000` |
| `--neutralization` | `SUBINDUSTRY` |
| `--decay` | `6` |
| `--delay` | `1` |
| `--min-sharpe` | `1.25` |
| `--min-fitness` | `1.0` |
| `--max-turnover` | `0.7` |
| `--max-correlation` | `0.7` |
| `--correlation-type` | `self` |
| `--output` | unset |

`--correlation-type` 可选：`self`、`ppac`、`prod`、`self_web`。

PASS 判定：

- `sharpe >= min_sharpe`
- `fitness >= min_fitness`
- `turnover <= max_turnover`
- correlation 可用且 `correlation <= max_correlation`

输入方式：

- 单个表达式：`--expression "<FASTEXPR>"`
- 多个表达式：`--file expressions.txt`，UTF-8，每行一个，空行和 `#` 注释跳过。

执行模板：

```bash
cd "$PROJECT_ROOT"
PYTHON_BIN=".venv/bin/python"; [ -x "$PYTHON_BIN" ] || PYTHON_BIN="python3"
PYTHONUNBUFFERED=1 "$PYTHON_BIN" -u validate_operator_wqbkit.py \
  --expression "rank(close)" \
  --neutralization SUBINDUSTRY \
  --decay 6 \
  --output validation_results.json
```

结果展示：

- 逐条展示 `PASS` 或 `FAIL`。
- 展示 `alpha_id`、`sharpe`、`fitness`、`turnover`、correlation、失败原因。
- 如果有 `--output`，把 JSON 路径交付给用户。

## 自定义 BRAIN API 任务

优先复用项目里的 `machine_lib.py`；若只需一次性查询，可用 `python - <<'PY'` 写临时内联脚本。

核心 API 常量：

- `API_BASE_URL = "https://api.worldquantbrain.com"`
- `DEFAULT_TIMEOUT = 60`
- `PAGE_SIZE = 50`
- `MAX_POLL_ATTEMPTS = 300`

认证：

- 使用 `requests.Session()`。
- `session.auth = (WQB_USERNAME, WQB_PASSWORD)`。
- `POST https://api.worldquantbrain.com/authentication`。
- 登录成功状态码按源项目经验是 `201`；`response.raise_for_status()` 也应保留。
- 可选 Persona 生物验证时，服务端可能返回 `401` 且 `WWW-Authenticate: persona`，需要打开 `Location` 指向的验证链接让用户完成后再继续。

可靠性策略：

- `_request_with_retry` 处理 `ReadTimeout`、`ConnectionError`、`429`、`5xx`。
- `429` 优先读取 `Retry-After`；没有时按 `base_backoff * (attempt + 1)` 等待。
- 轮询 `Location` 时使用 `_poll_with_retry_after`，最多 300 次。
- 翻页查询字段时每页 `limit=50`，页间 sleep `0.5s`。
- 同批提交模拟时每条间隔 sleep `0.3s`，降低限流概率。

常用函数行为：

- `get_datasets(s, instrument_type="EQUITY", region="USA", delay=1, universe="TOP3000")`：GET `/data-sets`，返回 DataFrame。
- `get_datafields(s, ..., dataset_id="", search="")`：GET `/data-fields`，支持 `dataset.id` 或 `search`，分页返回 DataFrame。
- `process_datafields(df)`：要求列 `id` 和 `type`；MATRIX 字段直接使用，VECTOR 字段用 `vec_avg`、`vec_sum` 包装；最终统一包装为 `winsorize(ts_backfill(field, 120), std=4)`。
- `first_order_factory(fields, ops_set)`：为字段生成一阶表达式；时间序列窗口默认 `[5, 22, 66, 120, 240]`。
- `single_simulate(alpha_pool, neut, region, universe, start)`：按批 POST `/simulations`，payload 为 `type=REGULAR`、`language=FASTEXPR`，轮询 `Location`，状态 `COMPLETE` 或 `WARNING` 视为完成。
- `get_alphas(start_date, end_date, sharpe_th, fitness_th, region, alpha_num, usage)`：GET `/users/self/alphas`，按日期和指标筛选，`usage=submit` 时只取正向；其他 usage 还会取负向并反转表达式。
- `prune(next_alpha_recs, prefix, keep_num)`：按字段前缀和 Sharpe 正负分桶，每桶保留前 `keep_num`。
- `get_group_second_order_factory(first_order, group_ops, region)`：为一阶表达式生成分组二阶表达式。
- `trade_when_factory(op, field, region)`：使用成交量、收益、趋势、新闻/情绪/期权事件生成 `trade_when(open_event, field, exit_event)`。
- `check_submission(alpha_bag, gold_bag, start)`：调用 `/alphas/{alpha_id}/check`，无失败检查则加入候选。
- `locate_alpha(s, alpha_id)`：GET `/alphas/{alpha_id}`，读取 `dateCreated`、Sharpe、Fitness、Turnover、Margin、Decay、表达式。

模拟 payload 模板：

```json
{
  "type": "REGULAR",
  "settings": {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 6,
    "neutralization": "SUBINDUSTRY",
    "truncation": 0.08,
    "pasteurization": "ON",
    "testPeriod": "P0Y",
    "unitHandling": "VERIFY",
    "nanHandling": "ON",
    "language": "FASTEXPR",
    "visualization": false
  },
  "regular": "rank(close)"
}
```

多模拟 payload 与单模拟相同，但 body 是多个 simulation object 组成的 list；源项目 `multi_simulate` 使用 `testPeriod = "P2Y"`。

## 表达式工厂参考

时间序列窗口：

- 一般时间序列操作：`[5, 22, 66, 120, 240]`
- 复合时间序列操作：`[5, 22, 66, 240]`

一阶操作规则：

- 原字段会直接作为表达式候选。
- `ts_percentage(field, d, percentage=0.5)`。
- `ts_decay_exp_window(field, d, factor=0.5)`。
- `ts_moment(field, d, k=2|3|4)`。
- `ts_entropy(field, d, buckets=10)`。
- `signed_power(field, 2)`。
- `ts_*` 和 `inst_tvr` 按时间窗口展开。
- vector 操作默认配合 `cap`。

分组表达式使用的 group：

- `market`、`sector`、`industry`、`subindustry`
- `bucket(rank(cap), range='0.1, 1, 0.1')`
- `bucket(rank(assets),range='0.1, 1, 0.1')`
- `bucket(group_rank(cap, sector),range='0.1, 1, 0.1')`
- `bucket(group_rank(assets, sector),range='0.1, 1, 0.1')`
- `bucket(rank(ts_std_dev(returns,20)),range = '0.1, 1, 0.1')`
- `bucket(rank(close*volume),range = '0.1, 1, 0.1')`
- USA 额外 group：`pv13_h_min2_3000_sector`、`pv13_r2_min20_3000_sector`、`pv13_r2_min2_3000_sector`、`pv13_h_min2_focused_pureplay_3000_sector`。

`trade_when` 通用入场事件：

- `ts_arg_max(volume, 5) == 0`
- `ts_corr(close, volume, 20) < 0`
- `ts_corr(close, volume, 5) < 0`
- `ts_mean(volume,10)>ts_mean(volume,60)`
- `group_rank(ts_std_dev(returns,60), sector) > 0.7`
- `ts_zscore(returns,60) > 2`
- `ts_arg_min(volume, 5) > 3`
- `ts_std_dev(returns, 5) > ts_std_dev(returns, 20)`
- `ts_arg_max(close, 5) == 0`
- `ts_arg_max(close, 20) == 0`
- `ts_corr(close, volume, 5|20) > 0|0.3|0.5`
- `ts_regression(returns, field, 5|20, lag = 0, rettype = 2) > 0`
- `ts_regression(returns, ts_step(5|20), 5|20, lag = 0, rettype = 2) > 0`

退出事件：

- `abs(returns) > 0.1`
- `-1`

区域事件：

- USA：`rp_css_business`、`mws82_sentiment`、`nws48_ssc`、`mws50_ssc`、`scl12_alltype_buzzvec`、`pcr_oi_270`。
- ASI：`mws38_score`。
- EUR：`rp_css_business`、`oth429_research_reports_fundamental_keywords_4_method_2_pos`、`mws84_sentiment`、`mws85_sentiment`、`mdl110_analyst_sentiment`、`nws3_scores_posnormscr`、`mws36_sentiment_words_positive`。
- GLB：`mdl109_news_sent_1m`、`nws20_ssc`、`nws20_bee`、`nws20_qmb`。
- CHN：`oth111_xueqiunaturaldaybasicdivisionstat_senti_conform`、`oth111_gubanaturaldaydevicedivisionstat_senti_conform`、`oth111_baragedivisionstat_regi_senti_conform`。
- KOR：`mdl110_analyst_sentiment`、`mws38_score`。
- TWN：`mdl109_news_sent_1m`、`rp_ess_business`。

## 可用操作符摘要

源项目可用操作符共 66 个：

- Arithmetic：`abs`、`add`、`densify`、`divide`、`inverse`、`log`、`max`、`min`、`multiply`、`power`、`reverse`、`sign`、`signed_power`、`sqrt`、`subtract`。
- Cross Sectional：`normalize`、`quantile`、`rank`、`scale`、`winsorize`、`zscore`。
- Group：`group_backfill`、`group_mean`、`group_neutralize`、`group_rank`、`group_scale`、`group_zscore`。
- Logical：`and`、`equal`、`greater`、`greater_equal`、`if_else`、`is_nan`、`less`、`less_equal`、`not`、`not_equal`、`or`。
- Time Series：`days_from_last_change`、`hump`、`kth_element`、`last_diff_value`、`ts_arg_max`、`ts_arg_min`、`ts_av_diff`、`ts_backfill`、`ts_corr`、`ts_count_nans`、`ts_covariance`、`ts_decay_linear`、`ts_delay`、`ts_delta`、`ts_mean`、`ts_product`、`ts_quantile`、`ts_rank`、`ts_regression`、`ts_scale`、`ts_std_dev`、`ts_step`、`ts_sum`、`ts_zscore`。
- Transformational：`bucket`、`trade_when`。
- Vector：`vec_avg`、`vec_sum`。

## 可用数据集摘要

账号在 `EQUITY / USA / delay=1 / TOP3000` 下记录的数据集：`analyst4` 1324、`fundamental2` 766、`fundamental6` 886、`model16` 24、`model51` 16、`news12` 875、`news18` 121、`option8` 64、`option9` 74、`pv1` 24、`pv13` 165、`socialmedia12` 18、`socialmedia8` 4、`univ1` 6。

## 排障

- 登录失败：确认 `.env` 的 `WQB_USERNAME` / `WQB_PASSWORD`，不要从 shell 环境或历史文件猜凭据。
- `401`：重新登录；如返回 Persona challenge，把验证链接交给用户完成。
- `429`：读取 `Retry-After`，降低并发，必要时把 `--simulations-per-batch` 降到 1。
- `5xx` / timeout / connection error：指数退避后重试，保留断点。
- 轮询无结果：确认 `Location` header 是否存在；轮询上限到达时记录 alpha/URL/阶段，不要无限等待。
- 字段为空：确认 region、universe、delay、dataset id、字段类型和账号权限。
- 工作流 C 不可用：检查 `wqbkit==0.4.7`、`DB_ENABLE` 和数据库配置；必要时改用工作流 B 或直接 POST `/simulations`。
- 提交检查失败：检查 `/alphas/{alpha_id}/check` 返回的 `is.checks`，重点看 `SELF_CORRELATION` 和其他 FAIL 项。

## 测试与变更约束

如果修改了源项目代码，必须运行：

```bash
pytest test_machine_lib.py test_alpha_machine.py test_config.py test_validate_operator_wqbkit.py -q
```

测试必须 mock 网络请求，不要在单测里访问真实 BRAIN API。修改 skill 文档本身时，至少验证 frontmatter 可解析、正文非空、且没有残留外部 reference/script 依赖。
