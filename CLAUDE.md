# LT-Sentinel — 会话续接说明

> 本文件在新 Claude Code 会话拉起时自动加载。**先把这页读完再动手**。
>
> **项目根**:`D:\Hackathons\lablab-techex-track1-lobstertrap\`(本文件所在目录)
> **早期 notes**:`01-lobstertrap-notes.md` / `02-design-and-mistakes.md` / `03-unresolved-questions.md`(2026-05-11,可选读)
> **当前权威设计**:`DESIGN.md`(2026-05-15,**以这份为准**)
> **LT 源码**:`./lobstertrap/`(只读参考,不改不 fork)

## 任务

Lablab.ai TechEx Hackathon Track 1 (Agent Security & AI Governance),单人队。
**真 deadline:2026-05-19 08:00 CST**(2026-05-15 18:50 实测 lablab Event Schedule "End of Submissions!")。
**Video Presentation 限制:最多 5 分钟,MP4 格式**(2026-05-15 实测 lablab Submission Guidelines)。
**Live on-stage pitching:2026-05-20 03:45 CST**(参考)。
原"deadline 今天"是用户自己给自己设的两天限制,非 lablab 官方,已澄清。
项目:LT-Sentinel = 在 Veea Lobster Trap 上加一层 sidecar,做跨事件统计监控(OER / EWMA / CUSUM)检测长期攻击。

## 必读

1. `DESIGN.md` — 完整设计文档。**§11(已拍板) + §12(校准方法) 必读**
2. `lobstertrap/README.md` + `lobstertrap/CLAUDE.md` — LT 实际能力(已 clone,只读参考,不改)
3. (内部记忆索引省略,仅供作者本地会话使用)

## 关键决策(已锁,不要回头讨论)

- **形态**:Sentinel 独立进程,不改 LT 源码
- **通信**:Sentinel tail LT 的 jsonl audit log(上行)+ 替换 policy YAML 文件 LT 热加载(下行)
- **三档**:信任 / 观察 / 戒严,LT policy YAML 三份预写,Sentinel 切档时整份替换 `policy_current.yaml`
- **连坐制**:LT policy condition 不支持 `agent_id`,切档全局生效。Sentinel 端仍 per-agent 维护 TrustScore(可视化 + audit 仍 per-agent)
- **TrustScore 公式**:`TrustScore = clamp(1 - (EWMA_OER - μ) / (3σ), 0, 1)`,μ/σ 来自 dev 实测
- **阈值**:τ_high = 0.33,τ_low = 0.10(归一化空间,锁定)
- **校准参数**:λ=0.2 / k=0.5σ / h=4σ / N=30 / ARL₀≈100,均带文献出处见 §12.1

## 环境状态(2026-05-15 18:50 实测)

- ✅ **Ollama** 在跑(:11434),模型可用:qwen3:8b / qwen2.5:7b / qwen3-vl:8b
- ✅ **Go 1.26.3** 已装(`C:\Program Files\Go\bin\go.exe`,2026-05-15 18:45 实测)。新 PowerShell/Bash 会自动有 PATH;若当前 shell 无,用全路径或 `export PATH="/c/Program Files/Go/bin:$PATH"`
- ✅ **LT 二进制** 已 build:`lobstertrap/lobstertrap.exe`(2026-05-15 18:48,`go build -o lobstertrap.exe .` 走通,zero warning)
- ✅ LT 源码已 clone 到 `D:\Hackathons\lablab-techex-track1-lobstertrap\lobstertrap`(只读)

## 下一步动作(按顺序)

1. ~~装 Go~~ ✅ 完成
2. ~~build LT~~ ✅ 完成
3. **写 happy-path 脚本**(Sentinel 这边的事):
   - 模拟 AcmeCorp 正常使用 200 条请求链
   - agent 在 body 里声明 `_lobstertrap.agent_id` / `declared_*`
   - 通过 LT(:8080)调到 Ollama(:11434)
   - 收集 LT audit log
4. **写 violation 判定函数**:`violation = f(metadata.risk_score, mismatches.critical, action)` — 具体怎么组合等看实际分布
5. **跑 200 条,实测 μ_dev**:`μ = violation 数 / 200`,预期 ∈ [0.05, 0.10]
6. **算 σ_dev**:`σ = √(μ(1-μ)/30)` (p-chart 公式)
7. **代入 h_concrete = 4 × σ_dev**
8. **离线 replay 算 ARL₀**:不达 [50, 200] 就调 λ 或 h
9. **填回 DESIGN.md §11.2 / §12 占位数字**

## 行为约束(从 MEMORY 提炼,做不到则被骂)

- **不要互相夸夸**:用户原话"咱们可不能互相夸夸然后欢天喜地的造个toy出来啊"。要 push back,不要哄
- **不要架构幻觉**:任何"LT 能/不能做 X"的论断必须 read 源码验证。`lobstertrap/internal/policy/table.go` 的 `getFieldValue()` 是 condition 字段权威
- **不要无确认改代码**:大改动先汇报方案,等用户拍板
- **build/script 自己跑**:不让用户复制粘贴命令
- **不要自动给"工程师"恭维**:用户 2026-05-12 自认"没出新手村",别粉饰
- **数字带出处**:校准参数都要标文献,实测项标公式 + 套用方法,这是用户硬要求
- **简历 / 个人网站话题**:跟当前技术工作严格隔离,不主动跳频道
- **奉承雷达**:"挑不出刺/全覆盖"是反信号,要 dissent

## 提交物(2026-05-19 08:00 CST 截止)

Track 1 要求(来自 lablab 页面 2026-05-15 扫):
- Project Title / Short Desc / Long Desc / Tech Tags / Cover Image
- **Video Presentation:最多 5 分钟,MP4**(实测确认)
- Slide Presentation / Public GitHub Repo
- Demo Application Platform / Application URL
- 评分四项:Application of Technology / Presentation / Business Value / Originality
- Veea bonus:**declared-versus-detected intent mismatches**(LT 原生输出,白嫖)+ **audit trails a regulator could read**(对齐 §11.6 双 jsonl)

## 接手第一句怎么说

直接告诉新会话:"读 CLAUDE.md + DESIGN.md §11 §12,从下一步动作 step 1 开始"。
