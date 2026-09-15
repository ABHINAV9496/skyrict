# SKY-99 backend performance gates

- run: 2026-09-15T07:44:01.549422+00:00
- samples: 8, warmup: 3
- passed: 8/8

| Case | p95 (ms) | median (ms) | work stmts (med/max) | ref p95 (ms) | status |
| --- | --- | --- | --- | --- | --- |
| duplicates | 20.3 | 17.6 | 1/1 | - | PASS |
| cashflow_projection | 19.1 | 18.1 | 1/1 | 38.7 | PASS |
| cashflow_naive_loop | 37.9 | 36.2 | 6/6 | - | PASS |
| working_capital_series | 52.2 | 49.0 | 6/6 | - | PASS |
| working_capital_serial | 43.4 | 42.7 | 6/6 | - | PASS |
| report_cache_hit | 16.7 | 12.8 | 1/1 | - | PASS |
| report_aggregate_recompute | 14.7 | 14.5 | 1/1 | - | PASS |
| report_cache_miss | 26.6 | 23.9 | 3/3 | - | PASS |

- `duplicates`: ok
- `cashflow_projection`: ok
- `cashflow_naive_loop`: ok
- `working_capital_series`: ok
- `working_capital_serial`: ok
- `report_cache_hit`: ok
- `report_aggregate_recompute`: ok
- `report_cache_miss`: ok
