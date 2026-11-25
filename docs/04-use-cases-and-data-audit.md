# Use cases and data audit

This document answers one question: **does the demo hold every data set that the people who run a wind farm need for the questions they really ask?** It names those people, lists their questions, defines the measures behind the questions, and maps each question to the data. It also says what is in the data on purpose for an analyst or an agent to find, and what is left out.

You do not need to know the wind industry to use it. Terms are explained where they first appear.

## Contents

- [Conclusion of the audit](#conclusion-of-the-audit)
- [Who asks](#who-asks)
- [What was missing, and what was added](#what-was-missing-and-what-was-added)
- [The data sets](#the-data-sets)
- [How the data fits together](#how-the-data-fits-together)
- [Measures and how they are calculated](#measures-and-how-they-are-calculated)
- [What is in the data to be found](#what-is-in-the-data-to-be-found)
- [What is not modelled](#what-is-not-modelled)
- [Using the question bank to test a data agent](#using-the-question-bank-to-test-a-data-agent)

## Conclusion of the audit

The first delivery of Phase 1 answered questions about **now**: what each turbine is doing, which alarms are active, how the last hour went. That is the control room's view, and it is about a tenth of what a wind farm's staff ask.

Most real questions are about **a period**, **a comparison** or **money**: last month against the budget, this turbine against the fleet, this failure against the last one, the lost energy in dollars, the contract's guarantee against what was delivered. None of that could be answered, because the demo had no past, no plan and no contract.

The regenerated Phase 1 adds what was missing:

| Added | Why it is needed |
|---|---|
| Two years of operating history at the industry's standard 10-minute resolution | Every question about a period, a trend or a comparison |
| An availability log with standard categories, causes and responsibility | "Why did we lose production, and whose fault was it?" |
| Work orders with labour, parts, cost and waiting time; open and planned work | Maintenance planning, cost, the backlog |
| Oil analysis and blade inspection records | Condition of the two most expensive components |
| Curtailments and market prices | Lost revenue, and what the grid and the market did |
| A power forecast, kept up to date | Planning work in low wind; forecast quality |
| A budget, the contracts and the people | Budget against actual, guarantees, warranty, who to call |
| Turbines that carry their history into the live data | Questions that combine "now" with "normally" |

With these, the demo answers 43 questions from six roles. 39 are answered from the Lakehouse and 4 from live data; [05-question-bank.md](05-question-bank.md) lists them, and notebook `04_question_bank` holds a tested reference query for each of the 39.

All data is synthetic. The site, the companies and the people are fictional.

## Who asks

| Role | What the role is responsible for | Typical horizon |
|---|---|---|
| **Control room operator** | Watches the site live. Makes the first decision when an alarm comes in: wait, reset, limit, stop, call someone. | Minutes to hours |
| **Site manager** | Runs the site: production, availability, the work plan, the people, the cost. Reports to the owner every month. | Days to months |
| **Maintenance planner** | Decides which work is done when, by whom, with which parts, and picks the time that costs the least production. | Days to weeks |
| **Performance engineer** | Finds turbines that produce less than the wind allows, and explains why: misalignment, blade wear, icing, wakes, curtailment. | Weeks to years |
| **Reliability engineer** | Finds what fails and how often, sees a failure coming in temperatures, vibration and oil, and knows what it did last time. | Weeks to years |
| **Asset and commercial manager** | Answers to the owner and the bank: revenue, budget, contracts, guarantees, warranty, market, forecast quality. | Months to years |

## What was missing, and what was added

| Kind of question | Data it needs | In the first delivery | Now |
|---|---|---|---|
| What is happening now? | Live telemetry, alarms, states | Yes | Yes; the turbines now also carry three standing conditions |
| What does this alarm mean, and what do I do? | Alarm catalogue, procedures, on-call roster | Yes, for 17 alarm codes | 40 alarm codes; people behind the roster |
| How much did we produce, against budget? | History of energy; a budget | No | `ops_scada_10min`, `ops_monthly_budget` |
| How available were the turbines, and why not more? | States over time with a standard category and a cause | No | `ops_scada_10min`, `ops_turbine_events` |
| Which turbine underperforms, and since when? | Possible power next to actual power, over time | No | `ops_scada_10min` (possible power), `ref_power_curve`, `ops_met_10min` |
| What fails, how often, at what cost? | Failures with component, mode, duration; repair cost | Four work orders | `ops_turbine_events`, `ops_work_orders`, `ops_work_order_parts`, `ops_alarm_log` |
| Is something developing? | Long trends of temperature and vibration; oil and blade records | No | `ops_scada_10min`, `ops_oil_analysis`, `ops_blade_inspections` |
| Have we seen this before? | Past failures with findings | No | Work order findings, linked to events |
| When can we do the work? | Forecast; open and planned work; parts; people | Parts only | `ops_power_forecast`, `ops_work_orders`, `ref_spare_parts`, `ref_technicians` |
| What did curtailment cost us? | Curtailment instructions, reason, who pays | No | `ops_curtailments`, `ops_market_prices` |
| Are we on budget, and are the contracts kept? | Budget, contract terms, cost by who pays | Price only | `ops_monthly_budget`, `ref_contracts`, cost bearer on work orders |
| Is the component under warranty? | Warranty end per component | No | `ref_components`, `ref_contracts` |
| How good is the forecast? | Past forecasts next to actuals | No | `ops_power_forecast` (day-ahead, for every past day) |
| How much carbon dioxide did we avoid? | Grid emission intensity | No | `ref_site` |

## The data sets

Three groups. Live tables are in the Eventhouse and appear in the Lakehouse through shortcuts. Reference and history tables are Delta tables in the Lakehouse.

### Live, from the edge (Eventhouse)

| Table | One row is | Rate |
|---|---|---|
| `TurbineTelemetry` | The readings of one turbine at one moment: wind, power, speeds, angles, temperatures, vibration | Every 5 seconds per turbine |
| `WeatherObservations` | The met mast at one moment | Every 10 seconds |
| `AlarmEvents` | An alarm raised or cleared | As it happens |
| `TurbineStateChanges` | A turbine changing state, with the reason | As it happens |
| `AssetRegistry` | The description of an asset, as the edge reports it | Every 5 minutes |
| `EdgeHeartbeats` | The edge saying it is alive | Every minute |

### Reference (Lakehouse, `ref_`)

| Table | Content | Rows |
|---|---|---|
| `ref_site` | The site: capacity, location, time zone, contract price, grid emission intensity | 1 |
| `ref_turbines` | The 12 turbines with model, position and commissioning date | 12 |
| `ref_components` | 11 components per turbine with serial number, install date and warranty | 132 |
| `ref_alarm_codes` | Every alarm: severity, meaning, limit, what the controller does, the procedure | 40 |
| `ref_power_curve` | The manufacturer's power curve | 61 |
| `ref_spare_parts` | Spare parts with stock, reorder point, lead time and cost | 21 |
| `ref_technicians` | The 11 people of the site with role and certificates | 11 |
| `ref_oncall_roster` | Who is on call in which order | 8 |
| `ref_contracts` | Power purchase agreement, service agreement, drivetrain warranty, grid connection | 4 |
| `ref_sop_index`, `ref_sop_documents` | The standard operating procedures, with their full text | 7 |
| `ref_gis_features`, `ref_terrain_grid` | Map layers and terrain, for the 3D app of a later phase | 29 and 16,641 |

### Operating history (Lakehouse, `ops_`)

Created by notebook `02_generate_history`. The history starts on 1 January 2025 and ends when the notebook runs. Row counts are for a run in November 2026.

| Table | One row is | Rows | What you would find it in at a real site |
|---|---|---|---|
| `ops_scada_10min` | One turbine in one 10-minute period: averages of the signals, state, availability category, energy, possible energy, lost energy and its cause | 1.19 million | The SCADA historian |
| `ops_met_10min` | The met mast in one 10-minute period | 99,000 | The SCADA historian |
| `ops_turbine_events` | One stop or outage, from start to end, with category, cause, component, responsible party and lost energy | 1,700 | The availability log |
| `ops_alarm_log` | One alarm from raised to cleared | 7,200 | The SCADA alarm log |
| `ops_work_orders` | One job: preventive, corrective, inspection or oil sample; done, open or planned | 320 | The maintenance system |
| `ops_work_order_parts` | One spare part used on one job | 260 | The maintenance system |
| `ops_oil_analysis` | One laboratory result for a gearbox oil sample | 54 | The oil laboratory's reports |
| `ops_blade_inspections` | One finding on one blade | 42 | The inspection contractor's reports |
| `ops_curtailments` | One instruction to limit the site's output | 460 | The grid operator's and offtaker's instructions |
| `ops_market_prices` | One hour at the site's settlement point: day-ahead and real-time price | 16,500 | The market operator |
| `ops_power_forecast` | One hour of one forecast: wind and power with a low and a high value | 16,700 | The forecast provider |
| `ops_monthly_budget` | One month of the budget: energy, revenue and cost | 24 | The owner's financial model |

Column-level descriptions are in [data-contracts.md](data-contracts.md).

Three words that the tables use:

- **SCADA** (supervisory control and data acquisition) is the system that reads and controls the turbines. Wind farms store its data as 10-minute averages; almost all performance and reliability analysis in the industry is done on that resolution.
- **Curtailment** is an instruction to produce less than the wind allows. It comes from the grid operator when the lines are full, or from the buyer of the power when the market price is negative.
- **Possible power** is what the turbine would produce in the wind it has, according to the manufacturer's power curve. The difference to actual power is the starting point of nearly every analysis.

## How the data fits together

The data sets are not independent samples. They describe one site with one past.

**One weather.** The history, the live simulator and the forecast use the same weather model. The wind in the last rows of the history is the wind the turbines report live, and the forecast is a forecast of that same weather, with an error that grows with the horizon. Seasons, the daily cycle, fronts, icing and storms are in all three.

**The same twelve machines.** Each turbine has its own efficiency, runs a little warmer or cooler than its neighbours and has its own vibration level. These properties are the same in the history and live, whatever the random seed of a run.

**Cause and effect.** Every stop for a fault, for maintenance, for weather or for a grid outage in `ops_scada_10min` has an event in `ops_turbine_events`, and every curtailment has a row in `ops_curtailments`; every repair has a work order with labour and parts from `ref_spare_parts`; a part that is out of stock makes the repair wait for its lead time; work is done in working hours and not in wind above 18 m/s; scheduled maintenance is placed on days with little wind; curtailment for negative prices happens when `ops_market_prices` is negative.

**Keys.**

| To join | Use |
|---|---|
| Anything per turbine | `TurbineId` (`turbineId` in reference tables), `WT-01` to `WT-12` |
| History with the met mast or the forecast | `Timestamp`; forecast `TargetTime` is on the hour |
| An event with its work order | `ops_turbine_events.WorkOrderId`, `ops_work_orders.EventId` |
| An alarm with its meaning | `AlarmCode` with `ref_alarm_codes.alarmCode` |
| A work order with its parts and people | `WorkOrderId`; `PartId`; `LeadTechnicianId` with `ref_technicians.technicianId` |
| A component with its warranty | `ref_components.warrantyContractId` with `ref_contracts.contractId` |

All times are UTC. The site's time zone is in `ref_site.timezone`.

**Where "now" is.** The history ends when notebook 02 runs, and live data begins when the simulator starts. Run notebook 02 again before a demo so that the two meet. Joining the two into one continuous 10-minute series is part of Phase 2.

## Measures and how they are calculated

Different companies calculate these measures differently, and the differences are a common source of disputes. These are the definitions this demo uses. The reference queries in notebook `04_question_bank` implement exactly these.

| Measure | Definition | Columns |
|---|---|---|
| **Energy** | Energy delivered by the turbines, in MWh | `sum(EnergyKwh) / 1000` |
| **Possible energy** | What the turbines would have delivered in the wind they had, by the manufacturer's power curve at the air density of the moment | `sum(PossibleEnergyKwh) / 1000` |
| **Lost energy** | Possible energy minus energy, in periods when the turbine was stopped or limited. Each period has one cause. Periods of full performance and of too little wind count no loss. | `sum(LostEnergyKwh) / 1000` by `LossCause` |
| **Capacity factor** | Energy as a share of what the turbines would deliver at rated power all the time | Energy / (rated power × hours) |
| **Time-based availability** | Share of the time in which the turbine was not down for a fault or for maintenance | 1 − hours in `Forced outage`, `Scheduled maintenance`, `Planned corrective action` / hours with information |
| **Energy-based availability** | Share of the energy that was not lost to the turbine itself | Energy / (energy + lost energy with cause `Component fault`, `Scheduled maintenance`, `Corrective maintenance`, `Technical derate`) |
| **Contractual availability** | Availability as the service agreement counts it: faults that the grid or force majeure caused are excluded, scheduled maintenance counts only above 80 hours per turbine and year, and time outside the turbine's operating range is left out. Per contract year, 1 July to 30 June. | Question AM-03 |
| **Performance index** | Energy as a share of possible energy while the turbine ran without any limit. Below 1 means the turbine converts wind worse than its power curve says. | Energy / possible energy where `AvailabilityCategory = 'Full performance'` |
| **Mean time between failures** | Running hours per failure. A failure is a fault that needed a technician. | (Hours − downtime) / failures |
| **Mean time to repair** | Hours from the fault to the return to service, including waiting for access, parts and people | Downtime / failures |
| **Curtailment share** | Curtailed energy as a share of possible energy | Lost energy with cause `Grid curtailment` / (energy + all lost energy) |
| **Wind index** | Mean wind speed of a month, relative to the long-term mean for that month. Energy changes about twice as fast as the wind index. | `ops_met_10min.WindSpeed`, `ops_monthly_budget.LongTermWindSpeed` |
| **P50 and P90** | The energy that the owner's model expects to be exceeded in 50 and in 90 of 100 years. P50 is the budget; P90 is the cautious case that lenders use. | `ops_monthly_budget` |
| **Revenue** | Energy at the contract price, plus curtailed energy that the buyer pays for ("deemed generation") | (Energy + compensated curtailment) × `ref_site.ppaPriceUsdPerMwh` |
| **Captured price** | The average market price weighted by when the site produced. Lower than the plain average, because wind farms produce most when prices are low. | Σ(energy × real-time price) / Σ energy |
| **Forecast error** | Mean absolute difference between day-ahead forecast and possible power, as a share of the site's capacity | `ops_power_forecast` with `ForecastType = 'Day-ahead'` |
| **Preventive maintenance compliance** | Share of the preventive work that was done within a week of its planned date | `ops_work_orders` |
| **Repair cost per MWh** | Corrective maintenance paid by the owner, per MWh produced | `TotalCostUsd` where `CostBorneBy = 'Owner'` / energy |
| **Carbon dioxide avoided** | Energy times the average emission intensity of the grid | Energy × `ref_site.gridEmissionFactorKgCo2PerMwh` |

**Availability categories.** Every 10-minute record and every event has one category. The names follow the international standard for wind turbine availability, IEC 61400-26.

| Category | Meaning | In this data |
|---|---|---|
| Full performance | Running with no limit | Most of the time |
| Partial performance | Running with a limit | Curtailment; a derate by the controller |
| Technical standby | Briefly not producing for a technical routine | Untwisting the cables |
| Out of environmental specification | The weather is outside the operating range | Too little wind; storm above 25 m/s; ice on the blades |
| Requested shutdown | Stopped on instruction | Curtailment to zero |
| Out of electrical specification | The grid is outside its limits | Grid outage |
| Scheduled maintenance | Planned service | Two services a year and the yearly inspections |
| Forced outage | Stopped by a fault | Faults that reset by themselves, and faults that need a technician |
| Information unavailable | No data | Communication loss |

**Who pays.** `ops_work_orders.CostBorneBy` follows the contracts in `ref_contracts`: scheduled work is inside the fixed fee of the service agreement, repairs of the gearbox and main bearing are covered by the drivetrain warranty until it ends, and all other repairs are invoiced to the owner.

## What is in the data to be found

A history without anything in it would make every answer "all normal". These stories are planted. Each is something that happens at real wind farms, and each can be found from the data alone. Dates are relative to the day notebook 02 runs.

| Story | What happened | Where it shows | Questions |
|---|---|---|---|
| **WT-07: a gearbox bearing is wearing** | For about four months the high-speed bearing of the gearbox has been wearing. No alarm has been raised. | Bearing temperature and vibration drift away from the fleet; iron in the oil rises from sample to sample; a borescope inspection is planned in two weeks; one bearing kit is in stock. Live, WT-07 runs warmer and rougher than the fleet. | RE-05, RE-06, RE-07, SM-05, OP-03, OP-08 |
| **WT-02: the same failure, 14 months ago** | The same bearing failed on WT-02. The oil samples had warned for five months. The turbine was down for about ten days, four of them waiting for a crane, and the repair cost about 121,000 dollars, paid by the warranty. | The event, the work order with its findings and cost, the oil samples before and after | RE-07, RE-08, MP-03 |
| **The warranty ends** | The drivetrain warranty ends on 31 December 2026. A bearing replaced before that date is paid by the supplier; after it, by the owner. | `ref_components`, `ref_contracts` | RE-09 |
| **WT-05: misaligned since a repair** | The wind vane was replaced three months ago and not calibrated. The turbine has stood about 9 degrees off the wind since then and produces about 4 percent less. | Performance index drops in one step; the nacelle direction differs from the met mast; a calibration work order is open | PE-01, PE-03, PE-04, SM-05 |
| **WT-09: eroded blades** | The leading edges of two blades are eroded. Output has fallen slowly to about 4 percent below the fleet. The repair waits for two calm, warm days. | Performance index falls gradually; power curve below the fleet at every wind speed; inspection findings of category 4; a repair is planned | PE-01, PE-02, PE-04, RE-10 |
| **WT-10: a repeat offender** | The pitch system of WT-10 trips more often than any other component on any turbine, and several times it needed a technician. A valve was replaced five months ago. | Event counts by turbine and component | RE-02, RE-03 |
| **WT-03: a fan that failed slowly** | A generator cooling fan failed over about three months. The generator ran hot and the controller limited power on hot, windy days, until the fan was replaced 11 weeks ago. | Alarms `GEN-WIND-TEMP-…` on one turbine only; lost energy with cause `Technical derate` | RE-04, SM-04 |
| **Waiting for parts** | Some repairs took one to three weeks because the part was not in stock. Two of those parts are at or below their reorder point today. | `WaitingForPartsHours` on work orders; stock and lead time | MP-03, MP-04, SM-06 |
| **The guarantee was missed** | In the contract year from July 2025 to June 2026 the turbines were a little less available than the 97 percent that the service provider guarantees. Liquidated damages are due. | Contractual availability | AM-03 |
| **Curtailment is the largest loss** | The site loses about 5 percent of its possible energy to curtailment: more than to all faults together. About half is paid for. | Lost energy by cause; curtailments by reason | SM-04, AM-02 |
| **Low prices when the wind blows** | The market price at the site's settlement point is negative in about one hour in ten, mostly in windy hours. The fixed contract price protects the site. | Captured price against average price | AM-06 |
| **Repairs against the budget** | For a history that ends in late 2026, corrective maintenance paid by the owner is about 15 percent over its budget for the year. | Cost by bearer against the budget | AM-04 |
| **Two overdue jobs** | Two tower bolt checks have been postponed twice for high wind. | Open work orders with a planned date in the past | SM-05, MP-02 |
| **Winter** | Ice on the blades in cold, damp weather and shutdowns in storms cost several percent of the energy of the winter months. | Lost energy by month and cause | PE-06, PE-07 |
| **Wakes and terrain** | Turbines behind others get less wind from some directions; turbines on the ridge get more. | Turbine wind against mast wind by direction | PE-05 |

The numbers behind these stories vary a little with the day the history ends. The stories around the service guarantee hold for a history that ends before July 2027; after that, the last complete contract year is a different one, in which the guarantee was met.

[question-bank-example-answers.md](question-bank-example-answers.md) shows every answer for one run.

**To demonstrate after 31 December 2026 with the warranty still running,** regenerate the reference data with a later end date, copy it to the VM, upload it and run notebook 01 again:

```bash
PYTHONPATH=simulator python3 -m windfarm_sim.sitegen --out data/reference --seed 42 --drivetrain-warranty-end 2027-12-31 &&
bash infra/vm.sh push &&
bash infra/vm.sh ssh bash ./edge/scripts/07-sync-reference-data.sh
```

## What is not modelled

Left out on purpose. Say so if someone asks; do not let an agent guess.

| Not in the data | What a real site would have |
|---|---|
| Electrical losses and the revenue meter | A meter at the grid connection. Energy there is 2 to 3 percent less than the sum of the turbines. This demo treats the sum of the turbines as the sold energy. |
| Vibration spectra | A condition monitoring system with frequency bands per bearing and gear stage. This demo has one overall vibration value per gearbox. |
| History at the resolution of the live data | The history is 10-minute data; live data is 5-second data. The history does not contain the faults you inject live. |
| Health, safety and environment records | Incidents, near misses, permits to work, wildlife and noise restrictions |
| A shift calendar | Who works when, absences, travel time. The data has the people, their roles and who led each job. |
| Purchasing | Purchase orders and deliveries. The data has stock, reorder point and lead time. |
| Full finance | Actual fixed costs, debt service, tax credits, insurance claims. The budget has a fixed-cost line with no actuals next to it. |
| Market settlement | Day-ahead schedules, imbalance charges, ancillary services |
| A forecast per turbine | The forecast is for the site. |

## Using the question bank to test a data agent

The question bank is the test set for the data agent of Phase 3.

1. Run notebook `04_question_bank`. Its results are the expected answers for your data on that day.
2. Ask the agent the questions in the words of [05-question-bank.md](05-question-bank.md), then in your own words.
3. Compare. Three kinds of difference are worth separating:

   | Difference | Usual cause | Fix |
   |---|---|---|
   | A different number for the same measure | The agent used another definition: for example, it counted too-little-wind as unavailable, or averaged percentages instead of dividing sums | Put the definitions of this document into the agent's instructions |
   | A wrong table or join | The agent did not know which table holds what | Describe the tables to the agent; give it the reference queries as examples |
   | A different period | "Last month" or "this year" read differently, or the agent used today's date while the history ends earlier | Tell the agent that all times are UTC and where the history ends |

4. Ask what the data cannot answer, from the table above, and check that the agent says so.

The reference queries are written in Spark SQL for a notebook. A data agent queries the Lakehouse through its SQL analytics endpoint, which uses T-SQL: the logic of the queries carries over, the date functions differ. Translating them is part of Phase 3.
