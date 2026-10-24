# Data dictionary

Source: [Amazon Last Mile Routing Research Challenge](https://registry.opendata.aws/amazon-last-mile-challenges/) (2021), training split, 6,112 routes from 17 US stations, 2018-07-19 → 2018-08-26. `ingest.py` turns the nested JSON into three flat tables.

The **Glossary** below is the context both LLM agents receive, and **Model terms** go to the analyst agent only (`agents.py` loads both sections). The SQL agent therefore answers from the source data, and the agents and this document always use the same terms.

## Glossary
- package: one parcel at one stop; one row of lm_packages, key (route_id, stop_id, package_id). Count packages, not routes, when a result is about packages.
- route: one van's delivery run on one day from one station; one row of lm_routes.
- stop: one place on a route; one row of lm_stops, key (route_id, stop_id). type 'Station' is the depot itself (visit_order 0, never has packages); type 'Dropoff' is a customer stop. Do not filter on type unless the question is about stops.
- station: the delivery station (depot) a route starts from = lm_routes.station_code, 17 values such as DLA3. "Station" in a question means station_code.
- failed delivery: scan_status <> 'DELIVERED', i.e. 'DELIVERY_ATTEMPTED' or 'REJECTED'. Fail rate = share of packages with a failed delivery (about 0.76% overall).
- time window: the customer's delivery slot tw_start to tw_end; both NULL when the package has none (has_time_window = false for about 92% of packages).
- planned_service_time_seconds: planned time to hand the package over at the stop.
- depth_cm, height_cm, width_cm, volume_cm3: parcel dimensions. They are package sizes, not distances.
- executor_capacity_cm3: the van's load capacity. Load ratio = total_volume_cm3 / executor_capacity_cm3.
- route_score: Amazon's quality rating of the driven route: 'High', 'Medium', 'Low'. Known only after the route.
- visit_order: the order in which the driver actually visited the stops. Known only after the route.

## Model terms
- risk: the model's predicted probability that a package's delivery fails.
- flagged: the riskiest 1% of the day's packages, saved for operator review. Flagged packages are a small subset, not all packages.
- actual_failed: the real outcome of a flagged package (1 = failed); the ground-truth check of a flag.
- lift: fail rate among flagged packages divided by the average fail rate of all scanned packages.
- held-out days ("today"): the newest 20% of days (2018-08-14 to 2018-08-26). The model never trains on them.

## Source files → tables

| File (training split) | Size | Becomes |
|---|---|---|
| `route_data.json` | 79 MB | `lm_routes` + `lm_stops` |
| `package_data.json` | 375 MB | `lm_packages` |
| `actual_sequences.json` | 10 MB | `lm_stops.visit_order` |
| `travel_times.json` | 1.8 GB | not used: stop-to-stop travel times are for route optimization, not delivery-failure risk |
| `invalid_sequence_scores.json` | <1 MB | not used: challenge scoring file |

The challenge's evaluation split (`eval_*`) has the same structure and is not used; the time-based holdout replaces it.

## lm_routes: one row per route (6,112)

| Column | Type | Meaning |
|---|---|---|
| `route_id` | string | Route key |
| `station_code` | string | Delivery station the route starts from |
| `route_date` | timestamp | Day of the route |
| `departure_ts` | timestamp | Van leaves the station (UTC) |
| `executor_capacity_cm3` | double | Van capacity |
| `route_score` | string | High / Medium / Low, after the route |
| `n_stops` | bigint | *Derived:* stops on the route |
| `n_packages` | bigint | *Derived:* packages on the route |
| `total_volume_cm3` | double | *Derived:* sum of package volumes |

## lm_stops: one row per stop (904,527)

| Column | Type | Meaning |
|---|---|---|
| `route_id`, `stop_id` | string | Key; `stop_id` is a two-letter code unique within a route |
| `type` | string | `Station` (depot) or `Dropoff` |
| `zone_id` | string | Delivery zone; NULL for the depot and for 6,515 dropoffs |
| `lat`, `lng` | double | Coordinates |
| `visit_order` | bigint | Actual visit order, after the route |
| `n_packages` | bigint | *Derived:* packages at the stop |

## lm_packages: one row per package at a stop (1,457,175)

| Column | Type | Meaning |
|---|---|---|
| `route_id`, `stop_id`, `package_id` | string | Key. 1,422 packages appear at two or more stops of one route (1,432 extra rows): attempted at one, delivered at another |
| `scan_status` | string | `DELIVERED`, `DELIVERY_ATTEMPTED`, `REJECTED`; the outcome the model predicts |
| `tw_start`, `tw_end` | timestamp | Customer time window; NULL if none |
| `planned_service_time_seconds` | double | Planned hand-over time |
| `depth_cm`, `height_cm`, `width_cm` | double | Parcel dimensions |
| `has_time_window` | boolean | *Derived:* `tw_end` is not NULL |
| `volume_cm3` | double | *Derived:* depth × height × width |

## Result tables (written by the jobs)

| Table | Written by | One row is |
|---|---|---|
| `risk_flags` | `model.py`, daily | A flagged package: `risk`, `actual_failed`, `station_code`, `scan_ts` |
| `model_metrics` | `model.py`, daily | One scan: AUC, baselines, flagged count, fail rates, lift |
| `daily_reports` | `pipeline.py`, daily | Model metrics + the analyst agent's finding, root cause, automation idea |
| `agent_results` | `eval.py` | One golden-set question: generated SQL, correct, repairs |
| `agent_metrics` | `eval.py` | One golden-set run: accuracy, execution rate, models |
| `agent_questions` | `app.py` | A question asked in the app, its SQL and the finding |

## Model features (known before the van leaves)

`station_code`, departure hour, day of week, `n_stops`, route packages, load ratio, stop packages, `has_time_window`, hours from departure to `tw_end`, `planned_service_time_seconds`, `volume_cm3`. Never used: `scan_status` (the target), `visit_order` and `route_score` (known only after the route).
