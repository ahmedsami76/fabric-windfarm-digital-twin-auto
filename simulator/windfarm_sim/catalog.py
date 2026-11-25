"""Master data shared by the reference files and the operating history.

Plain data, no imports: ``sitegen`` writes it to the reference CSV files and
``history`` uses the same values, so a part number, a technician or an alarm code
in the generated history always exists in the reference tables.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- spare parts
# partId, description, componentCode, quantityOnHand, reorderPoint, leadTimeDays, unitCostUsd, location
SPARE_PARTS = (
    ("SP-GBX-HSS-BRG", "Gearbox high-speed shaft bearing kit", "GBX", 1, 1, 21, 18500, "OM-01"),
    ("SP-GBX-OIL-320", "Gearbox synthetic oil ISO VG 320, 1000 L", "GBX", 2, 1, 5, 7200, "OM-01"),
    ("SP-GBX-FLT-10", "Gearbox oil filter element 10 micron", "GBX", 14, 6, 3, 310, "OM-01"),
    ("SP-GBX-CLR-FAN", "Gearbox oil cooler fan motor", "GBX", 2, 1, 10, 2400, "OM-01"),
    ("SP-GBX-UNIT", "Gearbox, complete exchange unit", "GBX", 0, 0, 140, 385000, "Regional depot"),
    ("SP-GEN-FAN", "Generator cooling fan assembly", "GEN", 2, 1, 12, 4100, "OM-01"),
    ("SP-GEN-BRG-DE", "Generator drive-end bearing", "GEN", 3, 1, 14, 5600, "OM-01"),
    ("SP-PIT-VLV", "Pitch proportional valve", "PIT", 4, 2, 9, 2950, "OM-01"),
    ("SP-PIT-ACC", "Pitch accumulator 20 L", "PIT", 6, 3, 7, 1250, "OM-01"),
    ("SP-HYD-PMP", "Hydraulic pump unit", "HYD", 1, 1, 18, 8800, "OM-01"),
    ("SP-HYD-OIL-46", "Hydraulic oil ISO VG 46, 200 L", "HYD", 3, 1, 4, 980, "OM-01"),
    ("SP-YAW-VANE", "Wind vane and anemometer set", "YAW", 5, 2, 4, 1900, "OM-01"),
    ("SP-YAW-DRV", "Yaw drive motor with brake", "YAW", 0, 1, 25, 9700, "Regional depot"),
    ("SP-YAW-PAD", "Yaw brake pad set", "YAW", 8, 4, 6, 720, "OM-01"),
    ("SP-CNV-IGBT", "Converter IGBT module", "CNV", 6, 2, 15, 3300, "OM-01"),
    ("SP-CNV-COOL", "Converter coolant pump", "CNV", 1, 1, 11, 2150, "OM-01"),
    ("SP-SNS-PT100", "PT100 temperature sensor", "GBX", 30, 10, 2, 85, "OM-01"),
    ("SP-SNS-ACC", "Drivetrain accelerometer", "GBX", 8, 3, 6, 640, "OM-01"),
    ("SP-BLD-LEP", "Blade leading-edge protection kit, one blade", "BLD", 4, 3, 20, 3900, "OM-01"),
    ("SP-BLD-RCP", "Blade lightning receptor", "BLD", 6, 3, 12, 450, "OM-01"),
    ("SP-BLD-LAM", "Blade laminate repair kit", "BLD", 2, 1, 10, 2600, "OM-01"),
)
PART_BY_ID = {p[0]: p for p in SPARE_PARTS}

# --------------------------------------------------------------------------- people
# technicianId, name, role, discipline, certifications, crew, onCallRole
TECHNICIANS = (
    ("TECH-01", "Maria Alvarez", "Lead wind technician", "Maintenance", "GWO BST;GWO ART;HV switching;Crane signaller", "A", "TECH-01"),
    ("TECH-02", "Daniel Okafor", "Wind technician", "Maintenance", "GWO BST;GWO ART;Hydraulics level 2", "A", "TECH-02"),
    ("TECH-03", "Priya Nair", "Wind technician", "Maintenance", "GWO BST;Blade repair level 2;Rope access", "B", "TECH-03"),
    ("TECH-04", "Lucas Meyer", "Wind technician", "Maintenance", "GWO BST;GWO ART;Converter level 2", "B", ""),
    ("TECH-05", "Hannah Kim", "Wind technician", "Maintenance", "GWO BST;Drone pilot;Blade inspection", "A", ""),
    ("TECH-06", "Omar Haddad", "Apprentice wind technician", "Maintenance", "GWO BST", "B", ""),
    ("ENG-01", "Elena Petrova", "Reliability engineer, drivetrain", "Engineering", "Vibration analyst category II;Oil analysis", "", "ENG-01"),
    ("ENG-02", "Samuel Wright", "Electrical engineer", "Engineering", "HV authorised person;Protection relays", "", "ENG-02"),
    ("OPS-01", "Grace Lindqvist", "Control room operator", "Operations", "NERC system operator", "", "OPS-01"),
    ("OPS-02", "Tomás Ferreira", "Control room operator", "Operations", "NERC system operator", "", "OPS-02"),
    ("MGR-01", "Rebecca Stone", "Site manager", "Management", "", "", "MGR-01"),
)
FIELD_TECHNICIANS = tuple(t[0] for t in TECHNICIANS if t[0].startswith("TECH"))
LABOR_RATE_USD_PER_HOUR = 95.0

# --------------------------------------------------------------------------- contracts
# One row per contract. Empty string = not applicable to that contract.
CONTRACT_COLUMNS = ("contractId", "contractType", "counterparty", "startDate", "endDate", "priceUsdPerMwh",
                    "guaranteedAvailabilityPct", "liquidatedDamagesUsdPerMwh", "scheduledMaintenanceAllowanceHoursPerTurbineYear",
                    "annualFeeUsd", "settlementPoint", "terms")
CONTRACTS = (
    ("CT-PPA-001", "Power purchase agreement", "Fabrikam Power Trading", "2021-07-01", "2036-06-30", 38.5, "", "", "",
     "", "HB_WEST",
     "As-generated, fixed price for 100% of metered output. Curtailment for economic reasons (negative "
     "real-time price) is paid as deemed generation at the contract price; curtailment instructed by the grid "
     "operator for congestion or reliability is not paid."),
    ("CT-SMA-001", "Service and maintenance agreement", "Contoso Turbines Service", "2021-07-01", "2031-06-30", "", 97.0,
     38.5, 80, 1008000, "",
     "Scheduled maintenance, remote monitoring and fault response for all 12 turbines at a fixed annual fee. "
     "Corrective repairs are invoiced in addition: labour at 95 USD per hour and parts at list price, unless the "
     "component is under warranty. Guaranteed time-based availability of 97% per contract year (1 July to "
     "30 June), averaged over the site. Forced outages and planned corrective work count as unavailable. "
     "Scheduled maintenance counts as available up to the allowance. Grid outages, curtailment, icing, high "
     "wind and force majeure such as lightning are excluded. Liquidated damages are paid on the energy lost "
     "below the guarantee, at the PPA price."),
    ("CT-WAR-001", "Component warranty, drivetrain", "Fabrikam Drivetrain", "2021-03-01", "2026-12-31", "", "", "", "",
     "", "",
     "Five-year warranty on gearbox and main bearing from commissioning, extended to 31 December 2026. Covers "
     "parts, labour and crane for defects reported before the end date; requires oil analysis at least every "
     "six months."),
    ("CT-INT-001", "Interconnection agreement", "Woodgrove Transmission", "2021-03-01", "2051-02-28", "", "",
     "", "", "", "HB_WEST",
     "Export capacity 50.4 MW at the Northwind Ridge 138 kV substation. The grid operator may limit output for "
     "congestion or reliability."),
)
PPA_PRICE_USD_PER_MWH = 38.5
GUARANTEED_AVAILABILITY_PCT = 97.0
# Monthly operating budget. Fixed: service agreement fee (84,000), land lease, insurance, site staff
# and utilities. Corrective: what the owner expects to be invoiced for repairs outside warranty.
BUDGET_FIXED_OPEX_USD_PER_MONTH = 178000.0
BUDGET_CORRECTIVE_USD_PER_MONTH = 20000.0

# --------------------------------------------------------------------------- alarm codes that appear only in history
# The live simulator raises the codes in alarms.py. A real controller knows many more; these are the
# ones the generated history uses. code, component, severity, description, sopId
EXTRA_ALARMS = (
    ("CNV-OVERCURRENT", "converter", "critical", "Converter overcurrent trip", "SOP-OPS-000"),
    ("CNV-IGBT-FAULT", "converter", "critical", "Converter IGBT module fault", "SOP-OPS-000"),
    ("CNV-COOL-FLOW", "converter", "critical", "Converter coolant flow low", "SOP-OPS-000"),
    ("GRID-VOLT-DIP", "grid", "critical", "Grid voltage dip, turbine tripped offline", "SOP-CUR-006"),
    ("GRID-LOSS", "grid", "critical", "Grid lost, turbine stopped", "SOP-CUR-006"),
    ("PIT-FOLLOW-ERR", "pitch system", "critical", "Pitch following error", "SOP-PIT-003"),
    ("PIT-ACC-PRESS", "pitch system", "critical", "Pitch accumulator pre-charge low", "SOP-PIT-003"),
    ("YAW-POS-ERR", "yaw system", "critical", "Yaw position sensor error", "SOP-YAW-004"),
    ("YAW-VANE-FAULT", "yaw system", "critical", "Wind vane signal fault", "SOP-YAW-004"),
    ("YAW-DRV-OVERLOAD", "yaw system", "critical", "Yaw drive motor overload", "SOP-YAW-004"),
    ("YAW-BRAKE-WEAR", "yaw system", "warning", "Yaw brake pad wear limit reached", "SOP-YAW-004"),
    ("GEN-OVERSPEED", "generator", "critical", "Generator overspeed", "SOP-OPS-000"),
    ("GEN-BRG-TEMP-HIGH", "generator", "critical", "Generator bearing temperature high", "SOP-GEN-002"),
    ("GEN-FAN-FAULT", "generator", "critical", "Generator cooling fan failure", "SOP-GEN-002"),
    ("GBX-FLT-DP-HIGH", "gearbox", "warning", "Gearbox oil filter differential pressure high", "SOP-GBX-001"),
    ("GBX-CLR-FAN-FAULT", "gearbox", "critical", "Gearbox oil cooler fan failure", "SOP-GBX-001"),
    ("HYD-OIL-LEVEL-LOW", "hydraulic system", "critical", "Hydraulic oil level low", "SOP-PIT-003"),
    ("HYD-PUMP-FAULT", "hydraulic system", "critical", "Hydraulic pump failure", "SOP-PIT-003"),
    ("SNS-TEMP-FAULT", "controller", "warning", "Temperature sensor signal out of range", "SOP-OPS-000"),
    ("CTL-WATCHDOG", "controller", "critical", "Controller watchdog restart", "SOP-OPS-000"),
    ("ENV-ICE-DETECTED", "environment", "info", "Ice detected on blades, turbine stopped", "SOP-OPS-000"),
    ("ENV-LIGHTNING-STRIKE", "blades", "critical", "Lightning strike registered on blade", "SOP-OPS-000"),
    ("COMMS-LOST", "scada", "warning", "Communication with turbine controller lost", "SOP-COM-005"),
)

# --------------------------------------------------------------------------- fault types used by the history
# class A: resets by itself within minutes. class B: a technician has to attend. class C: a part is replaced.
# alarmCode, componentCode, class, relative frequency, failure mode, work order summary, parts
FAULT_TYPES = (
    ("CNV-OVERCURRENT", "CNV", "A", 5.0, "Converter trip", "", ()),
    ("GRID-VOLT-DIP", "GRID", "A", 4.0, "Grid disturbance", "", ()),
    ("PIT-FOLLOW-ERR", "PIT", "A", 5.0, "Pitch following error", "", ()),
    ("YAW-POS-ERR", "YAW", "A", 3.0, "Yaw sensor glitch", "", ()),
    ("GEN-OVERSPEED", "GEN", "A", 1.5, "Overspeed in gusty wind", "", ()),
    ("CTL-WATCHDOG", "CTL", "A", 2.0, "Controller restart", "", ()),
    ("HYD-PRESS-LOW", "HYD", "A", 2.5, "Hydraulic pressure dip", "", ()),
    ("PIT-ACC-PRESS", "PIT", "B", 3.0, "Accumulator pre-charge loss", "Pitch accumulator recharged or replaced", ("SP-PIT-ACC",)),
    ("CNV-COOL-FLOW", "CNV", "B", 2.0, "Coolant pump wear", "Converter coolant pump replaced", ("SP-CNV-COOL",)),
    ("YAW-VANE-FAULT", "YAW", "B", 2.0, "Wind vane failure", "Wind vane and anemometer set replaced", ("SP-YAW-VANE",)),
    ("SNS-TEMP-FAULT", "GBX", "B", 3.0, "Sensor failure", "PT100 temperature sensor replaced", ("SP-SNS-PT100",)),
    ("HYD-OIL-LEVEL-LOW", "HYD", "B", 2.0, "Hydraulic hose leak", "Hydraulic hose replaced, oil topped up", ("SP-HYD-OIL-46",)),
    ("GBX-FLT-DP-HIGH", "GBX", "B", 2.0, "Filter clogged", "Gearbox oil filter replaced", ("SP-GBX-FLT-10",)),
    ("YAW-BRAKE-WEAR", "YAW", "B", 1.0, "Brake pad wear", "Yaw brake pads replaced", ("SP-YAW-PAD",)),
    ("CNV-IGBT-FAULT", "CNV", "C", 3.0, "IGBT module failure", "Converter IGBT module replaced", ("SP-CNV-IGBT",)),
    ("PITCH-ASYM-CRIT", "PIT", "C", 3.0, "Pitch valve sticking", "Pitch proportional valve replaced", ("SP-PIT-VLV",)),
    ("GEN-FAN-FAULT", "GEN", "C", 2.0, "Cooling fan bearing failure", "Generator cooling fan assembly replaced", ("SP-GEN-FAN",)),
    ("HYD-PUMP-FAULT", "HYD", "C", 1.5, "Hydraulic pump failure", "Hydraulic pump unit replaced", ("SP-HYD-PMP",)),
    ("YAW-DRV-OVERLOAD", "YAW", "C", 1.0, "Yaw drive motor failure", "Yaw drive motor replaced", ("SP-YAW-DRV",)),
    ("GBX-CLR-FAN-FAULT", "GBX", "C", 1.5, "Oil cooler fan failure", "Gearbox oil cooler fan motor replaced", ("SP-GBX-CLR-FAN",)),
)
COMPONENT_LABELS = {"ROT": "Rotor hub", "BLD": "Blade set", "PIT": "Pitch system", "MBR": "Main bearing",
                    "GBX": "Gearbox", "GEN": "Generator", "CNV": "Converter", "TRF": "Transformer",
                    "YAW": "Yaw system", "HYD": "Hydraulic unit", "TWR": "Tower", "CTL": "Controller",
                    "GRID": "Grid connection"}
# Yearly rates per turbine of each fault class, before the per-turbine factors below.
FAULT_RATE_PER_YEAR = {"A": 22.0, "B": 6.0, "C": 1.1}

# --------------------------------------------------------------------------- what makes each turbine an individual
# Standing conditions are true "now": the live simulator applies them, and the history builds up to them.
STANDING_CONDITIONS = (
    {"turbineId": "WT-07", "kind": "gearbox_wear", "oilTempAdd": 4.5, "bearingTempAdd": 6.0, "vibrationAdd": 1.3,
     "sinceDays": 130, "note": "High-speed shaft bearing wear, iron in oil rising"},
    {"turbineId": "WT-05", "kind": "yaw_offset", "offsetDeg": 9.0, "sinceDays": 96,
     "note": "Wind vane replaced and not calibrated"},
    {"turbineId": "WT-09", "kind": "blade_erosion", "efficiency": 0.968, "sinceDays": 600,
     "note": "Leading-edge erosion on blades A and C"},
)
# Relative fault frequency per turbine and component (1.0 where not listed).
FAULT_PRONE = {("WT-10", "PIT"): 2.6, ("WT-06", "CNV"): 1.9, ("WT-12", "YAW"): 1.7}
