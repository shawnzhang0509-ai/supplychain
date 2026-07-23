# main-gui 销量 SQL 模板（直接复制使用）

## 重要：为什么你那边「还是不行」

1. **如果 sales 导出报错，旧 CSV 不会被覆盖**  
   日志里出现 `sales ... error` 时，`output/<渠道>/Sales 8-30.csv` 等文件仍是上一次成功导出的旧数据，所以看起来「8-30 和 30 还是一样」。

2. **不要从网页/聊天里复制粘贴 SQL**  
   main-gui 还会把 `<`、`<=`、`>=`、`<>` 吃掉，粘贴时也容易重复一整段 SQL。请**整文件复制**本目录下的 `.txt`。

3. **文件名必须一致**（含空格）  
   - `sales 8-30.txt`
   - `sales 30.txt`
   - `sales 15.txt`

## 部署步骤（Windows）

1. 从本仓库下载整个 `sql/main-gui-templates/` 文件夹（或拉取 PR #11 分支）。
2. 用记事本 / VS Code 打开三个 `sales *.txt`，确认：
   - Transfer 段可用：`AND CASE WHEN t.TransferType = 'Order' THEN 0 ELSE 1 END = 1`
   - **全文搜索不到** `<` 或 `>` 字符
   - **第 133～145 行**（CheckinWindows）必须是：
     - `DATEADD(day, 8, ck.CheckinDate) AS SampleStart`（8-30 文件）
     - `CAST(GETDATE() AS DATE) BETWEEN DATEADD(...)`（不能是 `GETDATE() 0 THEN`）
     - `WHERE ck.rn BETWEEN 1 AND 3`（不能是 `ck.rn 3`）
   - 只有**一段** SQL（不要出现两套 `WITH ... SELECT`）
3. 覆盖 main-gui 配置目录里对应的三个模板文件。
4. 重新运行 main-gui，确认日志里 **sales 错误数为 0**。
5. 打开新生成的 CSV，第一列应有 `WindowType`：
   - `Sales 8-30.csv` → `8-30`
   - `Sales 30.csv` → `30`
   - `Sales 15.csv` → `15`
6. 同一 `CheckinDate` 下，`Sales 8-30.csv` 的 `SampleStart` 应比 `Sales 30.csv` 晚 7 天。

## 本地校验（可选）

在仓库根目录执行：

```bash
python scripts/validate_main_gui_sql.py sql/main-gui-templates
```

对你本机 main-gui 模板目录：

```bash
python scripts/validate_main_gui_sql.py "D:/你的工作目录/main-gui/templates"
```

全部显示 `OK` 再导出。

## 8-30 与 30 的逻辑差异

| 文件 | SampleStart | 取样区间 |
|------|-------------|----------|
| sales 8-30.txt | 入库日 + **8** 天 | 第 8～30 天 |
| sales 30.txt | 入库日 + **1** 天 | 第 1～30 天 |

若 `AvgDailyDemand_3Checkins_Avg` 仍完全相同，且 `SampleStart` 也相同，说明仍在使用旧模板或导出失败。

## 排查：Transfer 段对了但还是失败

你贴的这段 **本身没问题**。更常见是文件**其它位置**仍是被 main-gui 破坏过的旧代码：

| 搜索内容 | 正确 | 错误（被吃掉 `<` 后） |
|----------|------|-------------------------|
| 取样开始 | `DATEADD(day, 8, ck.CheckinDate) AS SampleStart` | 只有 `DATEADD(day, 1, ...)` 或根本没有 |
| 未满周期判断 | `GETDATE() AS DATE) BETWEEN DATEADD` | `GETDATE() 0 THEN` |
| 最近三次 | `WHERE ck.rn BETWEEN 1 AND 3` | `WHERE ck.rn 3` |

**快速隔离**：先把 `sales 8-30-po-only.txt` 重命名为 `sales 8-30.txt` 试跑一个渠道。若成功，问题在 `Transfers` 表字段；若仍失败，问题在 CheckinWindows 或其它段。


1. main-gui **最新一次**完整日志（含报错 SQL 片段）
2. 你本机 `sales 8-30.txt` 里 **第 90～100 行**（Transfer 那段 WHERE）
3. 任意一个渠道新生成的 `Sales 8-30.csv` 前几行（看是否有 `WindowType` 列）
