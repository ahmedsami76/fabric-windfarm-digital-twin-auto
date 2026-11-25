-- The questions the wind farm twin asks the Lakehouse when it has no service principal for the
-- Eventhouse (docs/11-deployment-guide-phase4.md). They read the shortcut tables of Phase 1, which
-- the Eventhouse writes at most every 5 minutes, so the newest row is minutes old.
--
-- Run them on the SQL analytics endpoint of WindFarmLH: open the Lakehouse, switch to
-- "SQL analytics endpoint" at the top right, New SQL query. Run one statement at a time.
-- The text of each statement is the text in app/overlay/packages/functions/src/live.ts; a test
-- compares the two. The KQL versions are in fabric/kql/94-twin-app-queries.kql.

-- 1. The newest row of every turbine in the last 60 minutes.
WITH newest AS (
  SELECT TurbineId, [Timestamp], State, WindSpeed, WindDirection, AmbientTemp, ActivePower, PowerSetpoint, RotorSpeed, PitchAngle, NacelleDirection, YawError, GearboxOilTemp, GearboxBearingTemp, GearboxOilPressure, GearboxVibration, GeneratorWindingTemp, GeneratorBearingTemp, MainBearingTemp, TransformerTemp, HydraulicPressure, TowerVibration,
         ROW_NUMBER() OVER (PARTITION BY TurbineId ORDER BY [Timestamp] DESC) AS rn
  FROM TurbineTelemetry
  WHERE [Timestamp] > DATEADD(minute, -60, SYSUTCDATETIME())
)
SELECT TurbineId, [Timestamp], State, WindSpeed, WindDirection, AmbientTemp, ActivePower, PowerSetpoint, RotorSpeed, PitchAngle, NacelleDirection, YawError, GearboxOilTemp, GearboxBearingTemp, GearboxOilPressure, GearboxVibration, GeneratorWindingTemp, GeneratorBearingTemp, MainBearingTemp, TransformerTemp, HydraulicPressure, TowerVibration
FROM newest
WHERE rn = 1
ORDER BY TurbineId;

-- 2. Alarms that were raised and have not cleared: what ActiveAlarms() of the KQL database returns.
WITH started AS (
  SELECT TOP 1 DATEADD(second, -CAST(UptimeSeconds AS int), [Timestamp]) AS StartedAt
  FROM EdgeHeartbeats
  ORDER BY [Timestamp] DESC
), newest AS (
  SELECT [Timestamp], TurbineId, AlarmCode, Status, Severity, Component, Description, Value, Threshold, Unit, SopId, AlarmId,
         ROW_NUMBER() OVER (PARTITION BY AlarmId ORDER BY [Timestamp] DESC) AS rn
  FROM AlarmEvents
  WHERE AlarmCode <> 'COMMS-RESTORED'
)
SELECT TOP 100 [Timestamp] AS RaisedAt, TurbineId, AlarmCode, Severity, Component, Description, Value, Threshold, Unit, SopId, AlarmId
FROM newest
WHERE rn = 1 AND Status = 'raised'
  AND ((SELECT StartedAt FROM started) IS NULL OR [Timestamp] >= DATEADD(minute, -1, (SELECT StartedAt FROM started)))
ORDER BY [Timestamp] DESC;

-- 3. The newest observation of the met mast.
SELECT TOP 1 [Timestamp], WindSpeed, WindDirection, WindGust, AmbientTemp, AirDensity
FROM WeatherObservations
WHERE [Timestamp] > DATEADD(minute, -60, SYSUTCDATETIME())
ORDER BY [Timestamp] DESC;

-- 4. The trend of one turbine, one row a minute (here WT-07, 60 minutes).
SELECT DATEADD(minute, DATEDIFF(minute, '2000-01-01', [Timestamp]), CAST('2000-01-01' AS datetime2(0))) AS [Timestamp], AVG(ActivePower) AS ActivePower, AVG(WindSpeed) AS WindSpeed, AVG(RotorSpeed) AS RotorSpeed, AVG(GearboxOilTemp) AS GearboxOilTemp, AVG(GearboxBearingTemp) AS GearboxBearingTemp, AVG(GearboxVibration) AS GearboxVibration
FROM TurbineTelemetry
WHERE [Timestamp] > DATEADD(minute, -60, SYSUTCDATETIME()) AND TurbineId = 'WT-07'
GROUP BY DATEADD(minute, DATEDIFF(minute, '2000-01-01', [Timestamp]), CAST('2000-01-01' AS datetime2(0)))
ORDER BY [Timestamp];

-- 5. The connection check: how much arrived in the last 60 minutes, and the newest row.
SELECT COUNT(*) AS [Rows], COUNT(DISTINCT TurbineId) AS Turbines, MAX([Timestamp]) AS Newest
FROM TurbineTelemetry
WHERE [Timestamp] > DATEADD(minute, -60, SYSUTCDATETIME());

