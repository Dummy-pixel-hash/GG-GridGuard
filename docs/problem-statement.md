# Problem Statement

**U1 — Power Outage Prediction & Grid Equipment Failure Advisor**

## Background

Power transformers and substations are the backbone of the transmission and
distribution grid — and the fleet is aging. Utilities increasingly instrument
these assets with condition monitoring: temperature, vibration, partial
discharge, and oil-quality sensors are already deployed and already measuring
failure signatures weeks before a breakdown. At the same time,
weather-driven stress (heat waves, storms, wind, heavy rainfall) is rising,
and weather is a known failure accelerator for already-degraded equipment.

## The Problem

Utilities run **calendar-based maintenance** on precisely the assets whose
condition is continuously measured. The data needed to see a failure coming
exists — sensor telemetry, weather forecasts, historical incident records —
but it lives in separate systems that never meet in time to act. The result:
a degraded transformer sails through a heat wave that nobody connected to its
rising temperature trend, and fails during peak load.

## Who Is Affected

- **Primary:** grid-operations and maintenance-planning teams at utilities —
  asset managers, reliability engineers, and dispatchers who must decide
  *which* assets to inspect, repair, or crew around, *this week*, with
  limited crews and budgets.
- **Downstream:** the millions of customers on the affected feeders —
  including hospitals, water-treatment plants, and other critical facilities
  — who experience the outage.

## Why It Matters

- Blackouts from transformer and substation failures cost utilities **$1M+
  per hour**, with incidents affecting millions of people.
- Failures that were visible weeks in advance become emergency repairs: more
  expensive, less safe, longer downtime.
- Crews spend hours on healthy assets (the calendar says so) while genuinely
  at-risk assets wait their turn.
- Weather-driven grid stress is increasing; reactive maintenance does not
  scale with it.

## Why Existing Solutions Fall Short

| Current approach | Why it falls short |
|---|---|
| Calendar-based maintenance | Ignores actual asset condition; healthy assets get serviced while sick assets wait |
| SCADA / condition-monitoring dashboards | Threshold alarms, not prediction — and they don't say *which* alarm matters most for the grid |
| Weather-risk tools | Assess the storm, not the assets — no link between forecast severity and specific equipment condition |
| Incident and reliability records | Used for post-mortems and reporting, not fused into forward-looking risk |
| Maintenance planning and crew scheduling | Disconnected from real-time condition and weather; plans are stale the moment conditions change |

The gap is not any single data source — it is **combination, in time to
act**. No current workflow fuses sensor condition + weather exposure +
incident history + asset degradation into a ranked, explainable, actionable
plan. That is the gap GridGuard is designed to close.
