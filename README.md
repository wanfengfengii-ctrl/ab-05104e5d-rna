# RNA 折叠裁决服务（纯后端）

供 RNA 探针设计团队复核候选序列的折叠裁决 API。研究员通过版本化 JSON
接口提交 RNA 序列与必须/禁止成对位置，获得一次**确定性**裁决。无前端。

## 裁决规则

合法结构必须同时满足：

1. 仅允许 `AU / UA / CG / GC / GU / UG` 六种碱基配对；
2. 配对位置至少相隔四位：`j - i >= 4`；
3. 每个位置至多参与一对；
4. 任意两对不得形成伪结（标准非交叉点括号结构）；
5. `must_pair` 中的位置必须成对、`must_not_pair` 中的位置必须不成对。

求解器使用**区间动态规划完整求解**（`app/solver.py`），按两级目标依次最大化：

1. 配对总数 `pair_count`；
2. 相邻堆叠对数 `stack_count`（`(i,j)` 与 `(i+1,j-1)` 同时存在计一次）。

不枚举全部结构、不做局部贪心：时间复杂度 O(n³)，空间 O(n²)，n=240 约
1–2 秒。多解时按点括号字符序 `(` < `.` < `)` 选定主结果，并返回另一份
同分最优见证；无可行结构返回 `INFEASIBLE`。

## 接口（版本前缀 `/api/v1`）

### `POST /api/v1/fold`

请求（位置为 1 基下标；`sequence` 长度 20–240，字符仅 `A/U/G/C`）：

```json
{
  "sequence": "AAAAAAAAAAAAAAAAAAAU",
  "must_pair": [],
  "must_not_pair": []
}
```

响应（多解示例；末位 `U` 可与第 1–16 位任一 `A` 配对，均为同分最优）：

```json
{
  "api_version": "v1",
  "verdict": "MULTIPLE_OPTIMAL",
  "sequence_length": 20,
  "primary": {
    "dot_bracket": "(..................)",
    "pairs": [{"left": 1, "right": 20}]
  },
  "scores": {"pair_count": 1, "stack_count": 0},
  "alternate": {
    "dot_bracket": ".(.................)",
    "pairs": [{"left": 2, "right": 20}]
  }
}
```

`verdict` 取值：

- `INFEASIBLE`：无可行结构，`primary`、`scores`、`alternate` 均为 `null`；
- `UNIQUE_OPTIMAL`：唯一最优，无 `alternate`；
- `MULTIPLE_OPTIMAL`：多解，`primary` 为字符序最小见证，`alternate` 为次小见证。

非法输入一律返回 `422` 与版本化错误信封，**不进入求解**：

```json
{"api_version": "v1", "error": {"code": "POSITION_OUT_OF_RANGE", "message": "..."}}
```

### `GET /healthz`

```json
{"status": "ok", "api_version": "v1"}
```

## 运行（Docker）

需要 Docker 20.10+（内置 Compose 子命令）。镜像基于 `python:3.13-slim`。

```bash
# 构建并启动 API；一次性验收服务在 API 健康后自动执行并退出
docker compose up --build

# 以验收服务退出码作为整条命令退出码（CI 友好）
docker compose up --build --abort-on-container-exit --exit-code-from acceptance

# 自定义宿主机端口
HOST_PORT=9090 docker compose up --build

# 单独重跑一次性验收（API 已在运行）
docker compose run --rm acceptance
```

`docker compose.yml` 包含：

- `api`：常驻 API，含容器健康检查与 Compose 健康条件，端口由
  `HOST_PORT`（默认 8080）配置；
- `acceptance`：**一次性**服务，等待 `api` 健康后通过 HTTP 跑完三类裁决、
  两级得分、字符序、约束、确定性、长度 240 与全部非法输入校验，输出报告退出。

## 本地开发

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
python -m scripts.acceptance     # 对本地 API 跑一次性验收
pytest                           # 单元 + 全枚举差分对照 + API 集成测试
```

`tests/test_solver_bruteforce.py` 在 n≤12 的随机序列与随机约束下全量枚举
所有非交叉结构，与 DP 输出的两级最优分、主/次见证逐项比对。
