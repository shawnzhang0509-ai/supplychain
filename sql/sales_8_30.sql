-- ============================================================
-- Sales 8-30 导出 SQL（修订版）
-- 占位符：{sku} = 渠道前缀，如 918
--
-- 修订要点：
-- 1. 销量日期优先用 PaidDateUtc（与 BI 一致），无则回退 DateCreatedUtc
-- 2. 入库事件按 Sku+Region+CheckinDate 去重（避免同 PO 多柜重复计数）
-- 3. 取样区间：入库后第8天 ~ 第30天（未满周期则到今天），含首尾
-- 4. 取样天数 = DATEDIFF(开始,结束)+1，与销量窗口严格一致
-- 5. 输出 SampleStart/SampleEnd/SampleDays/SampleQty 便于对账
-- 6. AvgDailyDemand_3Checkins_Avg 默认排除「未满30天的最近一次」，避免低估
-- ============================================================

WITH
-- ============================================
-- 1. 销量层
-- ============================================
DailySales AS (
    SELECT
        CAST(COALESCE(o.PaidDateUtc, o.DateCreatedUtc) AS DATE) AS OrderDate,
        p.Sku,
        CASE
            WHEN TRIM(w.Name) IN ('CHCH Gerald Connelly', 'GC', 'treffers', 'CHCH Treffers') THEN N'南岛'
            WHEN TRIM(w.Name) IN (
                'Hamilton Te Rapa', 'Carbine Rd Warehouse', 'Walls', 'Westgate Storage',
                'Walls Road', 'Walls in Transit', 'Hamilton Storage', 'Leonard Warehouse'
            ) THEN N'北岛'
            ELSE N'北岛'
        END AS Region,
        SUM(ol.Quantity) AS DailyQty
    FROM Orders o
    JOIN OrderLines ol ON ol.OrderId = o.Id
    JOIN Products p ON ol.ProductId = p.Id
    LEFT JOIN Warehouses w
        ON TRY_CAST(JSON_VALUE(ol.StockSnapshotJson, '$[0].WarehouseId') AS UNIQUEIDENTIFIER) = w.Id
    WHERE LEFT(p.Sku, 3) IN ('{sku}')
      AND COALESCE(o.PaidDateUtc, o.DateCreatedUtc) >= '2025-01-01'
      AND ISJSON(ol.StockSnapshotJson) = 1
      AND TRIM(w.Name) NOT IN (
          'CHCH Display', 'CHCH Display Colombo', 'CHCH Shop Storage', 'CHCH Colombo Shop Storage',
          'Onehunga Shop-Display', 'Onehunga Shop-Storage', 'Hamilton Shop Display',
          'Hamilton Old Display (No longer available)', 'Westgate display',
          'Presale-AKL', 'East Tamaki -Luo(No longer available)', 'Missing/To be located',
          '[Action Request]', '123 Jef', 'Onehunga warehouse(No longer available)'
      )
    GROUP BY
        CAST(COALESCE(o.PaidDateUtc, o.DateCreatedUtc) AS DATE),
        p.Sku,
        CASE
            WHEN TRIM(w.Name) IN ('CHCH Gerald Connelly', 'GC', 'treffers', 'CHCH Treffers') THEN N'南岛'
            WHEN TRIM(w.Name) IN (
                'Hamilton Te Rapa', 'Carbine Rd Warehouse', 'Walls', 'Westgate Storage',
                'Walls Road', 'Walls in Transit', 'Hamilton Storage', 'Leonard Warehouse'
            ) THEN N'北岛'
            ELSE N'北岛'
        END
),

-- ============================================
-- 2. 补货事件层
-- ============================================
RestockEvents_Raw AS (
    SELECT
        p.Sku,
        CASE
            WHEN c.ShippedtoportId = '3b9ff26b-4ec0-44c6-92ac-ee9804272426' THEN N'南岛'
            WHEN c.ShippedtoportId = '646a2216-87c2-4bc6-8469-fdbd90bb2d84' THEN N'北岛'
            ELSE N'北岛'
        END AS Region,
        CAST(c.ActualArrivingDate AS DATE) AS CheckinDate,
        c.ContainerNumber,
        po.PurchaseOrderCode,
        N'PO' AS SourceType
    FROM PurchaseOrders po
    JOIN PurchaseOrderLines pol ON pol.PurchaseOrderId = po.Id
    JOIN Products p ON pol.ProductId = p.Id
    LEFT JOIN Containers c ON c.PurchaseOrderId = po.Id
    WHERE p.Sku LIKE '{sku}%'
      AND c.ActualArrivingDate IS NOT NULL

    UNION ALL

    SELECT
        p.Sku,
        N'南岛' AS Region,
        CAST(t.CompletedOnUtc AS DATE) AS CheckinDate,
        NULL AS ContainerNumber,
        N'Transfer' AS PurchaseOrderCode,
        N'Transfer' AS SourceType
    FROM dbo.Transfers t
    JOIN dbo.Products p ON t.ProductId = p.Id
    LEFT JOIN dbo.Warehouses w_source ON t.SourceWarehouseId = w_source.Id
    LEFT JOIN dbo.Warehouses w_target ON t.TargetWarehouseId = w_target.Id
    WHERE w_target.Name = 'CHCH Gerald Connelly'
      AND w_source.Name = 'CHCH in transit'
      AND t.TransferJobStatus = 'Completed'
      AND p.Sku LIKE '{sku}%'
      AND t.TransferType <> 'Order'
),

-- 同一天同地区多次到港（多柜）合并为一次补货事件
RestockEvents AS (
    SELECT
        Sku,
        Region,
        CheckinDate,
        MAX(ContainerNumber) AS ContainerNumber,
        MAX(CAST(PurchaseOrderCode AS NVARCHAR(50))) AS PurchaseOrderCode,
        MAX(SourceType) AS SourceType
    FROM RestockEvents_Raw
    GROUP BY Sku, Region, CheckinDate
),

RestockEvents_Ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY Sku, Region ORDER BY CheckinDate DESC) AS rn
    FROM RestockEvents
),

-- ============================================
-- 3. 取样窗口（第8天含 ~ 第30天含；未满周期则到今天）
-- ============================================
CheckinWindows AS (
    SELECT
        ck.Sku,
        ck.Region,
        ck.CheckinDate,
        ck.ContainerNumber,
        ck.PurchaseOrderCode,
        ck.SourceType,
        ck.rn,
        DATEADD(day, 8, ck.CheckinDate) AS SampleStart,
        CASE
            WHEN CAST(GETDATE() AS DATE) < DATEADD(day, 30, ck.CheckinDate)
                THEN CAST(GETDATE() AS DATE)
            ELSE DATEADD(day, 30, ck.CheckinDate)
        END AS SampleEnd,
        CASE
            WHEN ck.rn = 1
                 AND CAST(GETDATE() AS DATE) < DATEADD(day, 30, ck.CheckinDate)
                THEN 1 ELSE 0
        END AS IsPartialPeriod
    FROM RestockEvents_Ranked ck
    WHERE ck.rn <= 3
),

-- ============================================
-- 4. 单次表现层
-- ============================================
SingleCheckinPerformance AS (
    SELECT
        cw.Sku,
        cw.Region,
        cw.CheckinDate,
        cw.ContainerNumber,
        cw.PurchaseOrderCode,
        cw.SourceType,
        cw.rn,
        cw.SampleStart,
        cw.SampleEnd,
        cw.IsPartialPeriod,

        CASE
            WHEN cw.SampleEnd < cw.SampleStart THEN 0
            ELSE DATEDIFF(day, cw.SampleStart, cw.SampleEnd) + 1
        END AS SampleDays,

        ISNULL(SUM(ds.DailyQty), 0) AS SampleQty,
        COUNT(DISTINCT CASE WHEN ds.DailyQty > 0 THEN ds.OrderDate END) AS DaysWithSales,

        CAST(
            ISNULL(SUM(ds.DailyQty), 0) * 1.0
            / NULLIF(
                CASE
                    WHEN cw.SampleEnd < cw.SampleStart THEN NULL
                    ELSE DATEDIFF(day, cw.SampleStart, cw.SampleEnd) + 1.0
                END,
                0
            )
        AS DECIMAL(18, 6)) AS SingleAvg_Daily

    FROM CheckinWindows cw
    LEFT JOIN DailySales ds
        ON cw.Sku = ds.Sku
       AND cw.Region = ds.Region
       AND ds.OrderDate >= cw.SampleStart
       AND ds.OrderDate <= cw.SampleEnd
    GROUP BY
        cw.Sku, cw.Region, cw.CheckinDate, cw.ContainerNumber, cw.PurchaseOrderCode,
        cw.SourceType, cw.rn, cw.SampleStart, cw.SampleEnd, cw.IsPartialPeriod
),

-- ============================================
-- 5. 最终聚合层
-- ============================================
FinalResult AS (
    SELECT
        scp.*,

        -- 主指标：排除「未满30天的最近一次」，避免拉低整体
        AVG(
            CASE
                WHEN NOT (scp.rn = 1 AND scp.IsPartialPeriod = 1)
                THEN scp.SingleAvg_Daily
            END
        ) OVER (PARTITION BY scp.Sku, scp.Region) AS AvgDailyDemand_3Checkins_Avg,

        -- 参考：3次简单平均（含未满周期）
        AVG(scp.SingleAvg_Daily) OVER (PARTITION BY scp.Sku, scp.Region) AS AvgDailyDemand_3Checkins_Avg_All,

        -- 参考：按销量/天数加权
        CAST(
            SUM(scp.SampleQty) OVER (PARTITION BY scp.Sku, scp.Region) * 1.0
            / NULLIF(SUM(scp.SampleDays) OVER (PARTITION BY scp.Sku, scp.Region), 0)
        AS DECIMAL(18, 6)) AS AvgDailyDemand_Weighted

    FROM SingleCheckinPerformance scp
)

-- ============================================
-- 6. 输出（导出 CSV 时可只保留需要的列）
-- ============================================
SELECT
    Sku,
    Region,
    CheckinDate,
    ContainerNumber,
    PurchaseOrderCode,
    rn AS CheckinRank,
    IsPartialPeriod,
    SampleStart,
    SampleEnd,
    SampleDays,
    SampleQty,
    DaysWithSales,
    SingleAvg_Daily,
    AvgDailyDemand_3Checkins_Avg,
    AvgDailyDemand_3Checkins_Avg_All,
    AvgDailyDemand_Weighted
FROM FinalResult
ORDER BY Sku, Region, CheckinDate DESC;
