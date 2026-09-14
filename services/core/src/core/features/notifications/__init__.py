"""Feature: core.notifications - unified notification center (SKY-93).

The centralized, batched notification surface for producers across every ERP
module (finance, inventory, payroll, approvals, compliance, AI anomalies).
See ``docs/architecture/adr/0007-notification-center.md`` and the M-NOTIF
walkthrough for the design.

Public seams:

- :class:`~core.features.notifications.producer.NotificationProducer` - the
  SDK modules call to emit an event. Idempotent by dedupe key per recipient,
  recipient resolution over explicit users / permission holders / role
  holders, and per-recipient channel selection honoring prefs plus the
  mandatory rule.
- :class:`~core.features.notifications.batching.NotificationBatchingService`
  + :class:`~core.features.notifications.worker.NotificationBatchingWorker` -
  collapse low/medium bursts into one digest per (module, category,
  recipient) within the config window.
- :class:`~core.features.notifications.service.NotificationService` - the
  inbox read model and user actions (mark read / read-all / snooze /
  preferences).
"""
