# skyrict-testing

Shared test utilities — fixtures, factories, and helpers for all Skyrict services.

## Usage

```toml
# In any service's pyproject.toml
[project]
dependencies = ["skyrict-testing"]
```

```python
from skyrict_testing.fixtures import rsa_private_key, rsa_public_key
from skyrict_testing.factories import UserFactory, TenantFactory, SessionFactory

# In your tests:
user = UserFactory()
tenant = TenantFactory()
```

## Generating RSA keys for tests

```bash
python -m skyrict_testing.generate_keys
# Creates tests/fixtures/rsa/{private,public}.pem
```

## Modules

| Module | Purpose |
|--------|---------|
| `fixtures` | `rsa_private_key`, `rsa_public_key`, `anyio_backend` pytest fixtures |
| `factories` | `UserFactory`, `TenantFactory`, `SessionFactory` (factory_boy) |
| `generate_keys` | CLI to generate RSA 2048-bit key pairs for RS256 JWT testing |
