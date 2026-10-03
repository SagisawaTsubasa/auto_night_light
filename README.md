# HA Auto Night Light（自动夜灯）

在设定时间自动将选定灯具切换到指定的色温与亮度；每盏灯有独立状态机，当前状态已符合预期时跳过控制，最大限度减少服务调用次数。Automatically switch selected lights to a target color temperature and brightness at a set time, with a per-light state machine that skips lights already matching the target.

## 功能

- 全可视化配置（config flow），无需手写 YAML
- 锚点时段模型：每个配置的时间是一个**锚点**，从该时刻起生效，直到下一个锚点——夜间开始 → 夜间参数，夜间结束 → 日间参数（可选），额外时段开始 → 额外时段参数
- 夜间开始、夜间结束两个锚点**各自独立选择来源**：固定时间 / 日落 / 日出，且偏移各自独立（-120 ~ +120 分钟）——比如 22:00 固定入夜、日出+15 分钟恢复日间
- 日出日落实体可选：默认内置 `sun.sun`（天文计算），也可选自定义实体（需提供 `next_rising`、`next_setting` 属性的 sun 或 sensor 实体）
- 额外时段（可选，**最多 5 个**）：每个时段单独一页配置（可选名称 + 开始时间 + 亮度 + 色温 + 过渡时长），从各自开始时间起生效，持续到下一个锚点
- **渐变过渡**（可选）：每个锚点可设过渡时长（0=立即切换），过渡带内亮度/色温按线性插值从上一时段参数渐变到目标参数；**定点调度**（只在步进点唤醒，带外零开销）+ **灯具原生渐变**（步进间由灯平滑滑变）；**尊重手动调节**——带内手动调过的灯不再被拉回，下个锚点归位
- 时间设置两页分离：第一页只做方式/开关选择，第二页只显示与选择相关的字段（选了固定时间才出时间选择器，选了日出日落才出偏移滑条）
- 日间模式（可选）：夜间结束后开灯自动应用日间亮度/色温
- 逐灯覆盖：选灯后为每盏灯单独开关，**只有打开的灯**才出现覆盖配置页，可覆盖夜间/日间/各额外时段的亮度与色温
- 每日定时触发（固定时间或日落），逐灯检查当前亮度 / 色温
- 开灯监听：任何选定灯**由关变开**时，自动按当前所处时段应用对应参数（可关闭；关闭后过渡带内开灯的灯由计划步接管判定处理——默认「尊重手动调节」下不会自动拉回曲线）
- 状态符合预期（在容差范围内）→ 直接跳过，不发送任何服务调用
- 状态不符 → 下发 `light.turn_on`，延迟后自动验证结果
- 支持二次编辑（集成条目 → 配置），可改灯具列表与全部参数
- 「仅调整已开启的灯」选项：关闭的灯不主动开灯
- 提供 `auto_night_light.trigger_now` 服务，可随时手动触发一轮检查
- 容差可调：亮度容差（0-25%）、色温容差（0-1000K）、验证延迟（0-60s）

## 状态机

每盏灯独立运行如下状态机：

```
IDLE ──定时触发──▶ PENDING ──┬─ 不可用 ──────────▶ OFFLINE
                             ├─ 关灯且仅调已开灯 ─▶ SKIPPED_OFF
                             ├─ 状态符合预期 ────▶ MATCHED（不控制）
                             └─ 状态不符 ────────▶ SETTING ──延迟验证──┬─▶ VERIFIED
                                                                        └─▶ MISMATCH（记日志）

开灯监听到 关→开 ──▶ TURN_ON_PENDING ──稳定延迟(可配)──▶ PENDING（按当前时段取参）
```

状态读取全部来自 HA 内部状态机缓存，不产生额外设备查询；只有真正不符的灯才会收到控制指令。开灯监听只响应「关→开」跳变，忽略运行中的属性变化，因此集成自己下发的控制不会形成触发循环。

## 时段模型

每个设置的时间是一个**锚点**：从该时刻起生效，直到下一个锚点。按 24 小时循环取「最近已过去的锚点」决定当前时段；同一时刻有多个锚点时**额外时段优先**：

- 夜间开始（固定时间，或日落+开始偏移）→ 夜间参数
- 夜间结束（固定时间，或日出+结束偏移）→ 日间参数（需开启日间模式），否则无效果
- 额外时段 i 开始（固定时间）→ 额外时段 i 参数

例：额外时段 1 为 18:00、夜间开始 22:00（固定）、夜间结束为日出+15 分钟 → 18:00–22:00 用额外时段 1 参数，22:00–次日日出+15 分钟用夜间参数，之后用日间参数（若启用）。跨夜自动支持。

### 渐变过渡

每个锚点可配置**过渡时长 T**（0=立即切换）。T>0 时，锚点时刻 A 往前推 T 分钟形成过渡带 [A−T, A]，带内参数按进度 f 从"带起点时刻的时段参数"线性插值到该锚点参数。例如夜间 23:30 开始、过渡时长 60 分钟，则 22:30 起逐步从日间参数过渡到夜间参数，23:30 完全到位。

- **定点调度引擎**（2.1.0）：步进时刻表每日构建一次（锚点触发/太阳事件变化/重载时刷新），每个步进点用精确定时器唤醒一次——带外零唤醒，步进精确对齐带边界；步进下发不再触发天文计算（开灯/锚点时刻的插值解析仍按需计算，日出漂移次日建表自动校准）
- **灯具原生渐变**：每步下发带 `transition=步进间隔秒`，步进之间由灯具硬件平滑滑变（不支持的灯自动忽略）；步进只调已亮的灯，**绝不主动开灯**
- **带入口语义**：入带第一步的预期值=带起点的时段参数。已在曲线上的灯跟随过渡；**不在曲线上的灯**（已处于目标参数、或被手动/自动化调过）视为手动状态——**整带不再干预**，保持现状
- **手动接管**：「尊重手动调节」开启（默认）时，带内被手动调离预期值超容差的灯立即停止干预，直到下个锚点归位；**关→开重新加入曲线**；手动调用「立即触发」服务也会立即归位。关闭该选项则回退旧行为（一律拉回曲线）
- 过渡带内开灯，直接应用该时刻的插值参数
- 起点参数取带起点时刻按纯锚点解析的模式快照；带内盖过其他锚点时一律忽略

时间来源说明：

- 默认实体 `sun.sun`：使用 HA 天文计算，日出日落随季节自动变化
- 自定义实体：读取实体的 `next_setting` / `next_rising` 属性，实体更新时自动重新调度
- 来源不可用（实体缺失/属性无效）时先回退 HA 内置天文计算，天文也不可用才回退到该锚点的固定时间

## 已知边界

- 重叠过渡带的边界分钟若不在胜出带步进网格上，该分钟无步进（缝隙 ≤1 个步进间隔，灯按上一目标的原生渐变滑到下一定时点）

## 安装

### HACS（推荐）

1. HACS → 自定义存储库 → 添加本仓库地址，类型选 Integration
2. 搜索「HA Auto Night Light」安装，重启 HA
3. 设置 → 设备与服务 → 添加集成 → 搜索「HA Auto Night Light」

### 手动

将 `custom_components/auto_night_light` 复制到 HA 配置目录的 `custom_components/` 下，重启后添加集成。

## 配置说明

### 第一页：时间设置（只做选择）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| 夜间开始方式 | 日落 | 固定时间 / 日落 / 日出 |
| 夜间结束方式 | 日出 | 即日间开始；固定时间 / 日落 / 日出 |
| 启用渐变过渡 | 关 | 打开后第二页才显示过渡相关滑条 |
| 夜间结束后应用日间参数 | 关 | 白天开灯自动切到日间参数 |
| 启用额外时段 | 关 | 开启后进入额外时段配置 |

### 第二页：时间详情（只显示相关字段）

| 参数 | 默认 | 显示条件 |
| --- | --- | --- |
| 夜间开始固定时间 | 22:00 | 开始方式=固定时间 |
| 夜间开始偏移 | 0 分钟 | 开始方式=日落/日出 |
| 夜间结束固定时间 | 06:00 | 结束方式=固定时间 |
| 夜间结束偏移 | 0 分钟 | 结束方式=日落/日出 |
| 日出日落实体 | sun.sun | 任一锚点为日落/日出 |
| 夜间开始过渡时长 | 0 分钟 | 启用渐变过渡；0=关闭 |
| 夜间结束过渡时长 | 0 分钟 | 启用渐变过渡且启用日间；0=关闭 |
| 渐变步进间隔 | 5 分钟 | 启用渐变过渡；1-15 分钟 |

### 额外时段（可选，每个一页）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| 数量 | 1 | 1-5 个 |
| 名称 | 空 | 可选，仅用于显示 |
| 开始时间 | 18:00 | 单时间锚点，持续到下一个锚点 |
| 亮度 / 色温 | 60% / 3000K | 该时段目标参数 |
| 过渡时长 | 0 分钟 | 0=立即切换；>0 则从上一时段参数线性渐变 |

### 灯具页

先多选灯具实体，下一页为每盏灯单独开关「逐灯额外设置」，只有打开的灯才会出现覆盖配置页。

### 各时段参数页

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| 夜间亮度 / 色温 | 25% / 2200K | 灯具不支持色温时仅校验亮度 |
| 日间亮度 / 色温 | 100% / 4000K | 启用日间时显示 |
| 亮度容差 | 4% | 偏差在此范围内视为符合 |
| 色温容差 | 150K | 同上 |
| 验证延迟 | 5s | 控制后多久复查状态 |
| 开灯后稳定延迟 | 1s | 0-10s，等灯具上报属性后再检查 |
| 开灯时自动应用 | 开 | 开灯时按当前时段检查并调整 |
| 仅调整已开启的灯 | 关 | 开启后关闭的灯不主动开灯 |
| 尊重手动调节 | 开 | 过渡带内被手动调离预期超容差的灯本带不再干预（首次偏离即停止纠正，连续 2 步判定接管；带入口仍单次判定）；下个锚点归位，关→开重新加入 |
| 渐变过渡 | 关 | 启用后时间详情页出现过渡时长/步进间隔 |
| 过渡曲线之外的提示 | — | 过渡带起点必须能解析出生效模式（日间模式开启，或更早的额外时段/夜间锚点），否则该带不生效 |

### 逐灯覆盖页（仅开关打开的灯）

每盏灯一页：夜间 + 日间（若启用）+ 每个额外时段各一对亮度/色温；页面内取消勾选则恢复使用全局值。

## 日志

运行日志走 HA 标准日志，调试可在 `configuration.yaml` 加：

```yaml
logger:
  logs:
    custom_components.auto_night_light: debug
```

## 兼容性

- Home Assistant 2026.1.0+（开发验证版本 2026.1.3）

## 作者

主程序：Kimi

## 更新日志 / Changelog

### 2.1.1（第二/三/四轮复审修复）
- 修复：接管判定改为**连续 2 步**偏离才生效——单步偏差（回读滞后、灯具色温能力边界）不再被误判成手动调节导致本带冻结  
  Takeover now requires 2 consecutive mismatched steps — single-step lags or device capability limits no longer freeze the band
- 修复：开灯 settle 与锚点路径下发失败时清空预期种子，下一步重试而不是误判接管放弃本带  
  Failed service calls on the settle/anchor paths clear the expected seed so the next step retries
- 修复：入带判定额外接受「我方最后成功下发的参数」——常亮灯跨时段边界不再被误判接管整段失效  
  Band-entry check also accepts the last params this integration applied — always-on lights no longer misjudged at period boundaries
- 修复：重叠过渡带按**窗口包含**去重（与插值路径同构，网格错位不再漏）；from_mode 不可解析的带同样占位；带锚点步与后继带同刻冲突时让位  
  Overlapping bands deduped by window containment (grid-misalignment proof); from_mode-unresolvable bands still claim their window; a band's anchor step yields to a later band covering it
- 修复：太阳实体分钟级漂移不再重置带身份（band_key 去掉分钟分量）；关→开与 settle 成功重置连续偏离计数；步进 gather 异常逐条落日志  
  Sun-entity minute drift no longer resets band identity; rejoin paths reset the mismatch counter; gather exceptions logged per light
- 修复：**手动调过的灯一次都不被拉回**——带内首次偏离即停止纠正，连续 2 步偏离才判接管（单步滞后自愈不触发；带入口仍单次判定）  
  A manually adjusted light is never pulled back: the first mismatch only observes, two consecutive mismatches trigger takeover (single-step lags self-heal; band entry stays single-judgment)
- 修复：重叠过渡带共享锚点分钟时的同刻重复下发（兜底按列表序去重，与时段平局规则一致）  
  Fixed duplicate same-minute steps when two bands share an anchor minute (list-order dedupe)
- 修复：自定义太阳实体的 next_* 属性为 datetime/None 时崩溃（entry 加载失败/日循环停摆）  
  Fixed crash when a custom sun entity exposes datetime/None next_* attributes
- 测试增至 25 项（真实服务载荷契约、连续计数与首步观测、滞后自愈、settle 失败清种、共享锚点去重、太阳 datetime 属性、句柄不泄漏）  
  25 tests incl. real service payload contract, consecutive counting with first-step observation, lag self-heal, settle-failure seed clearing, shared-anchor dedupe, sun datetime attribute, handle-leak

### 2.1.0（过渡引擎重做）
- **手动干涉尊重**：过渡带内被手动调离预期值的灯立即停止干预（本带内不再拉回），下个锚点归位、关→开重新加入曲线；新选项「尊重手动调节」默认开  
  Manual takeover: a light manually adjusted during a transition is left alone for the rest of the band; it rejoins at the next anchor or on off→on. New option, on by default
- **带入口语义**：入带时不在曲线上的灯（已处目标参数/被手动调过）整带跳过，不再被先拉高再拉回  
  Band-entry semantics: lights already off-curve at band entry skip the whole band instead of being yanked onto it
- **定点调度替代间隔轮询**：步进时刻表每日构建、精确唤醒，带外零唤醒，步进对齐带边界，天文计算退出热路径  
  Scheduled step points replace interval polling: daily plan, exact wake-ups, zero idle ticks, astronomy out of the hot path
- **灯具原生渐变**：步进下发带 `transition=步进间隔秒`，消除阶梯感  
  Native light fades between steps (`transition=` parameter)
- 过渡纯逻辑抽 `schedule.py` + 18 项测试（步进时刻表/插值/带定位/接管语义/带入口/监听清位）  
  Transition logic extracted to `schedule.py` with 18 tests

### 2.0.2
- 补记 2.0.1（未随版本文档化）：stop() 之后再不调度延迟动作、锚点刷新循环在停止后退出  
  Backfill 2.0.1 (was undocumented): delayed actions no longer scheduled after stop(); anchor refresh loop exits once stopped
- 修复：`translations/en.json` 与英文源 `strings.json` 对齐（此前缺 20 个 extra_{i}_* 翻译键，英文界面缺失字段文案）  
  Fixed: `translations/en.json` aligned with the English source `strings.json` (20 extra_{i}_* keys were missing)
- 清理：ruff 告警清零（import 排序、`int | float` 注解、否定条件直返）  
  Chores: ruff warnings cleared (import order, `int | float` annotation, direct negated return)
- 评估记录：V2.0 重构（223f7b6）已移除审查报告 §三 低-2 所指的 `current_mode()` 死代码，该项闭环  
  Note: the `current_mode()` dead code flagged by the audit (report §3 low-2) was already removed in the V2.0 rewrite — item closed

### 2.0.0 / 2.0.1（2026-09-05/07 审计修复批次）
- trigger_time 带默认值、迁移链清理、翻译补齐等审计修复；2.0.1 为停止防护 hotfix  
  September audit fixes (defaults, migration cleanup, translations); 2.0.1 was a stop-guard hotfix
