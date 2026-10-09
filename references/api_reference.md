# machine_lib API 参考（WorldQuant BRAIN）

来源：项目根 `machine_lib.py`。所有与 BRAIN API 的交互统一走该库，不要在业务脚本里重写 HTTP 逻辑。

## 凭证与登录

- 凭证从项目根 `.env` 读取：`WQB_USERNAME` / `WQB_PASSWORD`，加载函数 `config.load_wqb_credentials()`。
- 缺少键时抛 `RuntimeError: Missing required .env values`。
- 登录：`machine_lib.login()` → 带 `session.auth` 的 `requests.Session`。成功状态码是 **201**。
- `login_hk()`：处理可选 Persona 生物识别挑战（交互式输入，仅香港/特殊账号需要）。
- 调试时只打印 `username[:3] + "***"`，绝不打印密码或完整用户名。

## 网络可靠性（已踩过的坑，勿回退）

| 函数 | 用途 |
|---|---|
| `_request_with_retry(session, method, url, params=, json=, timeout=60, max_retries=10, base_backoff=2)` | 登录、拉字段、提交模拟等写操作；处理 429（读 `Retry-After`）、5xx、`ReadTimeout`、`ConnectionError`，指数退避 |
| `_poll_with_retry_after(session, url, timeout=60, max_attempts=300)` | 轮询直到响应无 `Retry-After` 头；用于模拟进度、alpha 详情、提交检查 |
| `_get_with_rate_limit(session, url, ...)` | GET + 429 重试，翻页用 |

- `DEFAULT_TIMEOUT = 60`；同批提交间隔 `sleep(0.3)`，翻页间隔 `sleep(0.5)`。
- 禁止 `while True` 裸轮询；禁止直接 `session.get/post` 不加重试。
- 后台运行输出会缓冲：用 `python -u` 或 `PYTHONUNBUFFERED=1`。

## 核心 API 速查

| 目的 | 函数 |
|---|---|
| 登录 | `login()` |
| 拉数据集列表 | `get_datasets(s, instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000')` |
| 拉数据字段（自动翻页） | `get_datafields(s, dataset_id='', search='', region='USA', universe='TOP3000', delay=1)` |
| 清洗字段（winsorize+ts_backfill+vec 包装） | `process_datafields(df)` → `["winsorize(ts_backfill(<id>, 120), std=4)"...]` |
| 一阶表达式工厂 | `first_order_factory(fields, ts_ops)`（basic_ops + ts_ops；days=[5,22,66,120,240]） |
| 单字段 ts 系列 | `ts_factory(op, field)` |
| 二阶分组 | `get_group_second_order_factory(exprs, group_ops, region)`；`group_factory(op, field, region)`（groups: market/sector/industry/subindustry/cap 分桶/资产分桶/波动率/流动性 + USA 专属 sector 组） |
| 三阶 trade_when | `trade_when_factory(op, field, region)`（open/exit 事件模板 + 区域事件：USA/ASI/EUR/GLB/CHN/KOR/TWN） |
| 分批（单模拟） | `load_task_pool_single(alpha_list, limit)` → 每批 limit 个 (alpha, decay) |
| 单模拟（带断点回调） | `single_simulate(pool, neut, region, universe, start, on_batch_done=None)` → failures 列表 |
| 多模拟（顾问模式） | `multi_simulate(pools, neut, region, universe, start)`；`load_task_pool(alpha_list, children, multi)` |
| 模拟数据组装 | `generate_sim_data(alpha_list, region, uni, neut)`（testPeriod=P2Y） |
| 按指标查 alpha | `get_alphas(start, end, sharpe, fitness, region, alpha_num, usage)`（usage: track/submit；按日期窗口 `dateCreated>` `<`，日期支持 MM-DD 或 YYYY-MM-DD） |
| 按字段前缀剪枝 | `prune(tracker, prefix, keep)` → 每个同字段保留 top keep 个 sharpe |
| 修改 alpha 属性 | `set_alpha_properties(s, alpha_id, name=, color=, tags=...)` |
| 提交前检查 | `check_submission(stone_bag, gold_bag, start, max_retries=2)` → gold_bag 追加 (alpha_id, self_corr) |
| 单条提交检查 | `get_check_submission(s, alpha_id)` → pc / "fail" / "error" / "sleep" |
| 查看 gold bag | `view_alphas(gold_bag)`（按 sharpe 降序打印） |
| alpha 详情 | `locate_alpha(s, alpha_id)` → [id, exp, sharpe, turnover, fitness, margin, dateCreated, decay] |
| 向量/复合/孪生字段工厂 | `vector_factory(op, field)`、`ts_comp_factory(op, field, factor, paras)`、`twin_field_factory(op, field, fields)` |

## 模拟请求结构（单条）

```json
{
  "type": "REGULAR",
  "settings": {
    "instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
    "delay": 1, "decay": 6, "neutralization": "SUBINDUSTRY",
    "truncation": 0.08, "pasteurization": "ON", "testPeriod": "P0Y",
    "unitHandling": "VERIFY", "nanHandling": "ON", "language": "FASTEXPR",
    "visualization": false
  },
  "regular": "<FASTEXPR>"
}
```

- 提交后从 `Location` 头取进度 URL，轮询直到 JSON 出现 `alpha`（ID）且 status 为 COMPLETE/WARNING。
- 模拟状态非 COMPLETE/WARNING 视为失败，记录 failures。

## 自定义模拟的常见 settings 搜索维度（alpha_explorer.py）

delay∈[1]、decay∈[0,3,7]、neutralization∈[MARKET,SECTOR,INDUSTRY]、truncation∈[0.05,0.08,0.1]、pasteurization∈[ON,OFF]、nanHandling∈[ON,OFF]。表达式模板按字段类型生成：price/return（ts_delta、ts_mean 比值、ts_std_dev、ts_rank、ts_av_diff、signed_power、ts_arg_max）、volume（ts_corr close、delta 乘积、and 事件）、fundamental（ts_rank、ts_zscore、ts_decay_linear、divide by close），通用（rank/zscore/ts_zscore/ts_delta/ts_sum/ts_delay），再叠加 group_neutralize/group_mean/group_rank × market/sector/industry。

## 测试

改动 `machine_lib.py` 后必须跑：`pytest test_machine_lib.py test_alpha_machine.py test_config.py -q`。测试用 `RecordingSession`/`FakeMachineLib` mock HTTP，不要在测试里发真实请求。
