-- ============================================================
-- Sales 8-30 诊断版：把取样区间、天数、销量、日均全部列出来
-- 用法：把 {sku} 换成渠道号，如 918
-- ============================================================

DECLARE @SkuPrefix VARCHAR(10) = '918';   -- 改成你的渠道，如 '918'
DECLARE @TargetSku VARCHAR(50) = NULL;      -- 可选：指定单个 SKU，如 '918-054'；NULL=全部

WITH
DailySales AS (
    SELECT
        CAST(o.DateCreatedUtc AS DATE) AS OrderDate,
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
    WHERE LEFT(p.Sku, 3) = @SkuPrefix
      AND (@TargetSku IS NULL OR p.Sku = @TargetSku)
      AND o.DateCreatedUtc >= '2025-01-01'
      AND ISJSON(ol.StockSnapshotJson) = 1
      AND TRIM(w.Name) NOT IN (
          'CHCH Display', 'CHCH Display Colombo', 'CHCH Shop Storage', 'CHCH Colombo Shop Storage',
          'Onehunga Shop-Display', 'Onehunga Shop-Storage', 'Hamilton Shop Display',
          'Hamilton Old Display (No longer available)', 'Westgate display',
          'Presale-AKL', 'East Tamaki -Luo(No longer available)', 'Missing/To be located',
          '[Action Request]', '123 Jef', 'Onehunga warehouse(No longer available)'
      )
    GROUP BY
        CAST(o.DateCreatedUtc AS DATE),
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

-- 若 BI 用 Paid Date，可对比这版（取消注释替换 DailySales）
-- DailySales AS (
--     SELECT CAST(o.PaidDateUtc AS DATE) AS OrderDate, ...
-- ),

RestockEvents AS (
    SELECT
        p.Sku,
        CASE
            WHEN c.ShippedtoportId = '3b9ff26b-4ec0-44c6-92ac-ee9804272426' THEN N'南岛'
            WHEN c.ShippedtoportId = '646a2216-87c2-4bc6-8469-fdbd90bb2d84' THEN N'北岛'
            ELSE N'北岛'
        END AS Region,
        CAST(c.ActualArrivingDate AS DATE) AS CheckinDate,
        c.ContainerNumber,
        CAST(po.PurchaseOrderCode AS VARCHAR(50)) AS PurchaseOrderCode,
        N'PO' AS SourceType
    FROM PurchaseOrders po
    JOIN PurchaseOrderLines pol ON pol.PurchaseOrderId = po.Id
    JOIN Products p ON pol.ProductId = p.Id
    LEFT JOIN Containers c ON c.PurchaseOrderId = po.Id
    WHERE p.Sku LIKE @SkuPrefix + '%'
      AND (@TargetSku IS NULL OR p.Sku = @TargetSku)
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
      AND p.Sku LIKE @SkuPrefix + '%'
      AND (@TargetSku IS NULL OR p.Sku = @TargetSku)
      AND t.TransferType <> 'Order'
),

RestockEvents_Deduped AS (
    SELECT
        Sku, Region, CheckinDate,
        MAX(ContainerNumber) AS ContainerNumber,
        MAX(PurchaseOrderCode) AS PurchaseOrderCode,
        MAX(SourceType) AS SourceType
    FROM RestockEvents
    GROUP BY Sku, Region, CheckinDate
),

RestockEvents_Ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY Sku, Region ORDER BY CheckinDate DESC) AS rn
    FROM RestockEvents_Deduped
),

CheckinWindows AS (
    SELECT
        ck.*,
        DATEADD(day, 8, ck.CheckinDate) AS PeriodStart,   -- 第8天（含）
        CASE
            WHEN CAST(GETDATE() AS DATE) < DATEADD(day, 30, ck.CheckinDate)
                THEN CAST(GETDATE() AS DATE)
            ELSE DATEADD(day, 30, ck.CheckinDate)
        END AS PeriodEnd,
        CASE
            WHEN ck.rn = 1
                 AND CAST(GETDATE() AS DATE) < DATEADD(day, 30, ck.CheckinDate)
                THEN 1 ELSE 0
        END AS IsPartialPeriod
    FROM RestockEvents_Ranked ck
    WHERE ck.rn <= 3
),

SingleCheckinPerformance AS (
    SELECT
        cw.Sku,
        cw.Region,
        cw.CheckinDate,
        cw.ContainerNumber,
        cw.PurchaseOrderCode,
        cw.SourceType,
        cw.rn,
        cw.PeriodStart,
        cw.PeriodEnd,
        cw.IsPartialPeriod,

        -- 取样天数：与销量窗口一致（含首尾）
        CASE
            WHEN cw.PeriodEnd < cw.PeriodStart THEN 0
            ELSE DATEDIFF(day, cw.PeriodStart, cw.PeriodEnd) + 1
        END AS SampleDays,

        -- 取样销量：第8天到结束日（含）
        ISNULL(SUM(ds.DailyQty), 0) AS SampleQty,

        -- 有销量的天数（辅助排查）
        COUNT(DISTINCT CASE WHEN ds.DailyQty > 0 THEN ds.OrderDate END) AS DaysWithSales

    FROM CheckinWindows cw
    LEFT JOIN DailySales ds
        ON cw.Sku = ds.Sku
       AND cw.Region = ds.Region
       AND ds.OrderDate >= cw.PeriodStart
       AND ds.OrderDate <= cw.PeriodEnd
    GROUP BY
        cw.Sku, cw.Region, cw.CheckinDate, cw.ContainerNumber, cw.PurchaseOrderCode,
        cw.SourceType, cw.rn, cw.PeriodStart, cw.PeriodEnd, cw.IsPartialPeriod
)

SELECT
    N'8-30' AS WindowType,
    Sku,
    Region,
    CheckinDate,
    ContainerNumber,
    PurchaseOrderCode,
    SourceType,
    rn AS CheckinRank,
    IsPartialPeriod,
    PeriodStart AS SampleStart,
    PeriodEnd AS SampleEnd,
    SampleDays,
    SampleQty,
    DaysWithSales,
    CAST(SampleQty * 1.0 / NULLIF(SampleDays, 0) AS DECIMAL(18, 6)) AS SingleAvg_Daily,

    -- 3次平均（含未满周期）
    AVG(CAST(SampleQty * 1.0 / NULLIF(SampleDays, 0) AS DECIMAL(18, 6)))
        OVER (PARTITION BY Sku, Region) AS AvgDailyDemand_3Checkins_Avg,

    -- 3次平均（排除未满30天的最近一次）
    AVG(CASE WHEN NOT (rn = 1 AND IsPartialPeriod = 1)
             THEN CAST(SampleQty * 1.0 / NULLIF(SampleDays, 0) AS DECIMAL(18, 6))
        END) OVER (PARTITION BY Sku, Region) AS AvgDailyDemand_MatureOnly,

    -- 验算：手动除一下看是否一致
    CAST(SampleQty AS VARCHAR(20)) + ' / ' + CAST(SampleDays AS VARCHAR(10)) AS QtyDivDays

FROM SingleCheckinPerformance
WHERE @TargetSku IS NULL OR Sku = @TargetSku
ORDER BY Sku, Region, CheckinDate DESC;

-- ============================================================
-- 附加：和 BI 对照 —— 某 SKU 在指定日期区间的总销量（不分入库批次）
-- ============================================================
/*
SELECT
    p.Sku,
    CASE
        WHEN TRIM(w.Name) IN ('CHCH Gerald Connelly', 'GC', 'treffers', 'CHCH Treffers') THEN N'南岛'
        ELSE N'北岛'
    END AS Region,
    SUM(ol.Quantity) AS TotalQty,
    COUNT(DISTINCT CAST(o.DateCreatedUtc AS DATE)) AS OrderDays
FROM Orders o
JOIN OrderLines ol ON ol.OrderId = o.Id
JOIN Products p ON ol.ProductId = p.Id
LEFT JOIN Warehouses w
    ON TRY_CAST(JSON_VALUE(ol.StockSnapshotJson, '$[0].WarehouseId') AS UNIQUEIDENTIFIER) = w.Id
WHERE p.Sku = '918-054'
  AND CAST(o.DateCreatedUtc AS DATE) BETWEEN '2026-07-10' AND '2026-07-23'
GROUP BY p.Sku,
    CASE
        WHEN TRIM(w.Name) IN ('CHCH Gerald Connelly', 'GC', 'treffers', 'CHCH Treffers') THEN N'南岛'
        ELSE N'北岛'
    END;
*/
