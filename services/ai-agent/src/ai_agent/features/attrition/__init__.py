"""HR attrition retention model + factor explanations (spec §6).

Slice layout: ``features`` (feature-vector → model input), ``model`` (a
v1 ``GradientBoostingClassifier`` + ``shap.TreeExplainer`` with a bundled
deterministic default), ``scorer`` (risk score + confidence + abstention +
top-3 factor contributions), ``model_card.json`` (committed), and ``cli``
(manual training/export — the platform deliberately has no scheduler).

The scorer is a deterministic, non-LLM computation. It NEVER calls the LLM
router or reads PII free text: core sends anonymous per-employee feature
vectors keyed by an opaque ``employee_ref``, and this package returns scores
+ factor contributions. Abstention (confidence < 0.75) drops low-confidence
rows instead of exposing them (spec §6).
"""
