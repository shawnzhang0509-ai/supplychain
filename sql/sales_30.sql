WITH 
-- ============================================
-- 1. 销量层
-- ============================================
DailySales AS (
    SELECT
        CAST(o.DateCreatedUtc AS DATE) AS OrderDate,
        p.Sku,
        CASE
            WHEN TRIM(w.Name) IN ('CHCH Gerald Connelly', 'GC', 'treffers', 'CHCH Treffers') THEN '南岛'
            WHEN TRIM(w.Name) IN ('Hamilton Te Rapa', 'Carbine Rd Warehouse', 'Walls', 'Westgate Storage', 'Walls Road', 'Walls in Transit', 'Hamilton Storage', 'Leonard Warehouse') THEN '北岛'
            ELSE '北岛'
        END AS Region,
        SUM(ol.Quantity) AS DailyQty
    FROM Orders o
    JOIN OrderLines ol ON ol.OrderId = o.Id
    JOIN Products p ON ol.ProductId = p.Id
    LEFT JOIN Warehouses w
        ON TRY_CAST(JSON_VALUE(ol.StockSnapshotJson, '$[0].WarehouseId') AS UNIQUEIDENTIFIER) = w.Id
    WHERE LEFT(p.Sku, 3) IN ('{sku}')
      AND o.DateCreatedUtc >= '2025-01-01'
      AND ISJSON(ol.StockSnapshotJson) = 1
      AND TRIM(w.Name) NOT IN (
          'CHCH Display', 'CHCH Display Colombo', 'CHCH Shop Storage', 'CHCH Colombo Shop Storage',
          'Onehunga Shop-Display', 'Onehunga Shop-Storage', 'Hamilton Shop Display', 'Hamilton Old Display (No longer available)', 'Westgate display',
          'Presale-AKL', 'East Tamaki -Luo(No longer available)', 'Missing/To be located', '[Action Request]', '123 Jef', 'Onehunga warehouse(No longer available)'
      )
    GROUP BY
        CAST(o.DateCreatedUtc AS DATE), p.Sku,
        CASE
            WHEN TRIM(w.Name) IN ('CHCH Gerald Connelly', 'GC', 'treffers', 'CHCH Treffers') THEN '南岛'
            WHEN TRIM(w.Name) IN ('Hamilton Te Rapa', 'Carbine Rd Warehouse', 'Walls', 'Westgate Storage', 'Walls Road', 'Walls in Transit', 'Hamilton Storage', 'Leonard Warehouse') THEN '北岛'
            ELSE '北岛'
        END
),

-- ============================================
-- 2. 补货事件层：统一两种来源，CheckinDate 统一转 DATE
-- ============================================
RestockEvents AS (
    -- 2A. 海外进货（PO/Container 到港）
    SELECT
        p.Sku,
        CASE
            WHEN c.ShippedtoportId = '3b9ff26b-4ec0-44c6-92ac-ee9804272426' THEN '南岛'
            WHEN c.ShippedtoportId = '646a2216-87c2-4bc6-8469-fdbd90bb2d84' THEN '北岛'
            ELSE '北岛'
        END AS Region,
        CAST(c.ActualArrivingDate AS DATE) AS CheckinDate,
        c.ContainerNumber,
        po.PurchaseOrderCode,
        'PO' AS SourceType
    FROM PurchaseOrders po
    JOIN PurchaseOrderLines pol ON pol.PurchaseOrderId = po.Id
    JOIN Products p ON pol.ProductId = p.Id
    LEFT JOIN Containers c ON c.PurchaseOrderId = po.Id
    WHERE p.Sku LIKE '{sku}%'
      AND c.ActualArrivingDate IS NOT NULL

    UNION ALL

    -- 2B. 北岛调拨到南岛（Transfers）
    SELECT
        p.Sku,
        '南岛' AS Region,
        CAST(t.CompletedOnUtc AS DATE) AS CheckinDate,
        NULL AS ContainerNumber,
        'Transfer' AS PurchaseOrderCode,
        'Transfer' AS SourceType
    FROM dbo.Transfers t
    JOIN dbo.Products p ON t.ProductId = p.Id
    LEFT JOIN dbo.Warehouses w_source ON t.SourceWarehouseId = w_source.Id
    LEFT JOIN dbo.Warehouses w_target ON t.TargetWarehouseId = w_target.Id
    WHERE 
        w_target.Name = 'CHCH Gerald Connelly'
        AND w_source.Name = 'CHCH in transit'
        AND t.TransferJobStatus = 'Completed'
        AND p.Sku LIKE '{sku}%'
        AND t.TransferType <> 'Order'
),

-- ============================================
-- 统一排序取最近 3 次
-- ============================================
RestockEvents_Ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY Sku, Region ORDER BY CheckinDate DESC) AS rn
    FROM RestockEvents
),

-- ============================================
-- 3. 单次表现层：计算 Checkin 后 30 天的销量表现（第1天~第30天）
-- ============================================
SingleCheckinPerformance AS (
    SELECT
        ck.Sku,
        ck.Region,
        ck.CheckinDate,
        ck.ContainerNumber,
        ck.PurchaseOrderCode,
        ck.rn,

        -- 计算总销量：只统计第 1 天到第 30 天的销量
        ISNULL(SUM(ds.DailyQty), 0) AS TotalQty_Period,

        -- 计算实际天数：
        -- 最近一次(rn=1)：取 (今天) 和 (入库后30天) 的较小值，减去 (入库当天)，最小为 0
        -- 历史数据(rn>1)：固定 30 天
        CAST(
            CASE
                WHEN ck.rn = 1 THEN
                    CASE
                        WHEN DATEDIFF(day, ck.CheckinDate, 
                            CASE WHEN CAST(GETDATE() AS DATE) < DATEADD(day, 30, ck.CheckinDate) 
                                 THEN CAST(GETDATE() AS DATE) 
                                 ELSE DATEADD(day, 30, ck.CheckinDate) 
                            END) < 0
                        THEN 0
                        ELSE DATEDIFF(day, ck.CheckinDate, 
                            CASE WHEN CAST(GETDATE() AS DATE) < DATEADD(day, 30, ck.CheckinDate) 
                                 THEN CAST(GETDATE() AS DATE) 
                                 ELSE DATEADD(day, 30, ck.CheckinDate) 
                            END)
                    END
                ELSE 30.0
            END
        AS FLOAT) AS ActualDays,

        -- 计算单次平均：总销量 / 实际天数
        ISNULL(SUM(ds.DailyQty), 0) /
        NULLIF(CAST(
            CASE
                WHEN ck.rn = 1 THEN
                    CASE
                        WHEN DATEDIFF(day, ck.CheckinDate, 
                            CASE WHEN CAST(GETDATE() AS DATE) < DATEADD(day, 30, ck.CheckinDate) 
                                 THEN CAST(GETDATE() AS DATE) 
                                 ELSE DATEADD(day, 30, ck.CheckinDate) 
                            END) < 0
                        THEN 0
                        ELSE DATEDIFF(day, ck.CheckinDate, 
                            CASE WHEN CAST(GETDATE() AS DATE) < DATEADD(day, 30, ck.CheckinDate) 
                                 THEN CAST(GETDATE() AS DATE) 
                                 ELSE DATEADD(day, 30, ck.CheckinDate) 
                            END)
                    END
                ELSE 30.0
            END
        AS FLOAT), 0) AS SingleAvg_Daily

    FROM RestockEvents_Ranked ck
    LEFT JOIN DailySales ds
        ON ck.Sku = ds.Sku
        AND ck.Region = ds.Region
        -- 核心：筛选销量日期在入库后第1天到第30天之间
        AND ds.OrderDate > ck.CheckinDate
        AND ds.OrderDate <= DATEADD(day, 30, ck.CheckinDate)
    WHERE ck.rn <= 3
    GROUP BY
        ck.Sku, ck.Region, ck.CheckinDate, ck.ContainerNumber, ck.PurchaseOrderCode, ck.rn
),

-- ============================================
-- 4. 最终聚合层
-- ============================================
FinalResult AS (
    SELECT
        Sku,
        Region,
        CheckinDate,
        ContainerNumber,
        PurchaseOrderCode,
        SingleAvg_Daily,
        AVG(SingleAvg_Daily) OVER (PARTITION BY Sku, Region) AS AvgDailyDemand_3Checkins_Avg
    FROM SingleCheckinPerformance
)

-- ============================================
-- 5. 输出结果
-- ============================================
SELECT
    Sku,
    Region,
    CheckinDate,
    ContainerNumber,
    PurchaseOrderCode,
    SingleAvg_Daily,
    AvgDailyDemand_3Checkins_Avg
FROM FinalResult
ORDER BY Sku, Region, CheckinDate DESC;
