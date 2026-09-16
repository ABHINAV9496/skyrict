# SKY-99 backend performance gates

- run: 2026-09-15T11:00:31.617870+00:00
- samples: 8, warmup: 3
- passed: 8/8

| Case | p95 (ms) | median (ms) | work stmts (med/max) | ref p95 (ms) | status |
| --- | --- | --- | --- | --- | --- |
| duplicates | 20.3 | 16.0 | 1/1 | - | PASS |
| cashflow_projection | 16.6 | 15.6 | 1/1 | 42.0 | PASS |
| cashflow_naive_loop | 47.0 | 41.4 | 6/6 | - | PASS |
| working_capital_series | 70.0 | 65.9 | 6/6 | - | PASS |
| working_capital_serial | 70.9 | 66.2 | 6/6 | - | PASS |
| report_cache_hit | 22.1 | 16.8 | 1/1 | - | PASS |
| report_aggregate_recompute | 19.6 | 19.1 | 1/1 | - | PASS |
| report_cache_miss | 40.1 | 34.2 | 3/3 | - | PASS |

- `duplicates`: ok
- `cashflow_projection`: ok
- `cashflow_naive_loop`: ok
- `working_capital_series`: ok
- `working_capital_serial`: ok
- `report_cache_hit`: ok
- `report_aggregate_recompute`: ok
- `report_cache_miss`: ok
