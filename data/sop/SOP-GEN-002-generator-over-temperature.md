# SOP-GEN-002: Generator winding over-temperature

| | |
|---|---|
| Site | Northwind Ridge Wind Farm (fictional demo site) |
| Owner | Electrical engineer (ENG-02) |
| Applies to | GEN-WIND-TEMP-HIGH, GEN-WIND-TEMP-CRIT, GEN-WIND-TEMP-TRIP |
| Component | Generator AE-DFIG-4500 (Adatum Electric) |
| Revision | 2, 2026-06-02 |

> Demo content. This procedure was written for a fictional site and must not be used to operate real equipment.

## Limits

| Signal | Normal at full load | Warning | Critical | Trip |
|---|---|---|---|---|
| Generator winding temperature | 95 to 115 degC | 125 degC | 140 degC, derate to 50% | 155 degC, stop |
| Generator bearing temperature | 55 to 68 degC | no alarm, used as evidence | | |

## Step 1: Confirm the fault

1. Compare winding temperature with the two nearest turbines at similar power. A difference above 15 degC at the same load is abnormal.
2. Check the generator bearing temperature. Winding and bearing rising together points to lost cooling air. Winding alone points to an electrical cause or a sensor.
3. Check ambient and nacelle temperature. On days above 35 degC the whole site runs warmer and several turbines may show warnings.

## Step 2: Act

| Condition | Action |
|---|---|
| Warning, one turbine | Curtail to 70% of rated power with approval of the on-call engineer. Review in 15 minutes. |
| Warning, several turbines on a hot day | No action. Note it in the log. |
| Critical | Keep the controller derate. Curtail to 50% so the limit stays after the controller releases it. Consult ENG-02, or ENG-01 out of hours. |
| Trip | Leave stopped until inspected. |

Winding temperature follows load closely. Halving the power typically brings the winding below the warning limit within 10 minutes when the cause is reduced cooling.

## Step 3: Follow-up

1. Raise a corrective work order. The most common cause on this fleet is failure of the cooling fan motor bearing (part SP-GEN-FAN). WT-03 had this failure in September 2026.
2. Inspect the air filters and the fan before the next high-wind period.

## Release criteria

Winding temperature below 115 degC for 15 minutes at the curtailed load, engineer approval and a work order on record.
