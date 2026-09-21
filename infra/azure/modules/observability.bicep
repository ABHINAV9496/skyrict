// =============================================================================
// SKY-114 - Observability module
//
// Cost-budget alerts at SUBSCRIPTION scope. Costs are the #1 risk for a
// free-trial beta that must run at ~$0/month, so this module alerts at 50%
// / 80% / 90% of a configurable monthly amount before any spend can sneak
// past the free allotments. (Microsoft.Consumption/budgets only exists at
// subscription or billing scope - it cannot be scoped to the resource group,
// which is why the deployment principal gets subscription-level Contributor
// in bootstrap-azure.ps1.)
//
// budgetStartDate is a parameter the CD passes as the first of the current
// month so re-applies within the same month are idempotent (a utcNow()
// fallback changes once per month boundary and is documented as the only
// intentional non-idempotent default).
// =============================================================================

targetScope = 'subscription'

@description('Deployment environment name (beta/staging/production) - used in alert names.')
param envName string

@description('Monthly budget amount in USD that triggers the percent alerts.')
param budgetAmount int = 10

@description('Percent thresholds at which to fire budget alerts.')
param budgetThresholds array = [
  50
  80
  90
]

@description('Email addresses receiving the budget alerts.')
param budgetContactEmails array = []

@description('Budget start date (YYYY-MM-DD). The CD passes the first of the current month for idempotent re-applies.')
param budgetStartDate string = utcNow('yyyy-MM-01')

@description('Budget end date - open-ended by default. Set when migrating to a committed period.')
param budgetEndDate string = '2099-12-31'

resource budget 'Microsoft.Consumption/budgets@2021-10-01' = [
  for threshold in budgetThresholds: {
    name: 'skyrict-${envName}-budget-${threshold}pct'
    properties: {
      amount: budgetAmount
      category: 'Cost'
      timeGrain: 'Monthly'
      timePeriod: {
        startDate: budgetStartDate
        endDate: budgetEndDate
      }
      notifications: {
        'alert${threshold}pct': {
          enabled: true
          operator: 'GreaterThanOrEqualTo'
          threshold: threshold
          thresholdType: 'Actual'
          contactEmails: budgetContactEmails
        }
      }
    }
  }
]
