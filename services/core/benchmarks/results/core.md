# SKY-99 backend performance gates

- run: 2026-09-15T04:05:10.118821+00:00
- samples: 3, warmup: 1
- passed: 8/8

| Case | p95 (ms) | median (ms) | work stmts (med/max) | ref p95 (ms) | status |
| --- | --- | --- | --- | --- | --- |
| duplicates | 16.3 | 16.3 | 1/1 | - | PASS |
| cashflow_projection | 16.5 | 16.5 | 1/1 | 38.4 | PASS |
| cashflow_naive_loop | 46.5 | 46.5 | 6/6 | - | PASS |
| working_capital_series | 54.9 | 54.9 | 6/6 | - | PASS |
| working_capital_serial | 51.5 | 51.5 | 6/6 | - | PASS |
| report_cache_hit | 18.9 | 18.9 | 1/1 | - | PASS |
| report_aggregate_recompute | 18.4 | 18.4 | 1/1 | - | PASS |
| report_cache_miss | 35.3 | 35.3 | 3/3 | - | PASS |

- `duplicates`: ok
- `cashflow_projection`: ok
- `cashflow_naive_loop`: ok
- `working_capital_series`: ok
- `working_capital_serial`: ok
- `report_cache_hit`: ok
- `report_aggregate_recompute`: ok
- `report_cache_miss`: ok
