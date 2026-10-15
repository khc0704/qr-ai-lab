"""System roles and the permission matrix.

Three system roles (``users.role``):

* ``superadmin`` – everything: resource pool, project quotas, delete projects, model zoo, user roles, GPU reset.
* ``admin``      – day-to-day operations only: review requests, stop / restart / reorder / delete jobs,
                   moderate the discussion board, read the admin dashboards. Cannot touch resources or delete projects.
* ``user``       – no administrative operation at all (project-level roles still apply).

The backend is the single source of truth: routers depend on ``require_perm("<perm>")`` and ``/me`` returns the
resolved permission list so the frontend only has to hide UI, never decide.
"""

from __future__ import annotations

from typing import Final

ROLES: Final[tuple[str, ...]] = ("superadmin", "admin", "user")
ADMIN_ROLES: Final[frozenset[str]] = frozenset({"superadmin", "admin"})

# permission → roles that have it
PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    # read-only admin area (dashboard, node, queue, audit, usage history, model zoo status)
    "admin.view": ADMIN_ROLES,
    "audit.view": ADMIN_ROLES,
    "usage.view": ADMIN_ROLES,
    "users.view": ADMIN_ROLES,
    # day-to-day operations
    "requests.review": ADMIN_ROLES,  # start review / approve / reject project requests
    "jobs.control": ADMIN_ROLES,  # stop / restart / delete / reorder any job
    "issues.moderate": ADMIN_ROLES,  # close / reopen / assign / delete discussion threads
    # superadmin only
    "pool.manage": frozenset({"superadmin"}),  # total resource pool + job defaults
    "quota.manage": frozenset({"superadmin"}),  # per-project quota
    "projects.delete": frozenset({"superadmin"}),
    "users.manage": frozenset({"superadmin"}),  # change system roles / activation
    "model_zoo.manage": frozenset({"superadmin"}),  # upload / import / delete pretrained weights
    "gpu.reset": frozenset({"superadmin"}),
}

ROLE_RANK: Final[dict[str, int]] = {"user": 0, "admin": 1, "superadmin": 2}


def permissions_for(role: str) -> list[str]:
    return sorted(perm for perm, roles in PERMISSIONS.items() if role in roles)


def role_has(role: str, perm: str) -> bool:
    if perm not in PERMISSIONS:  # unknown permission name = programming error, never silently allow
        raise KeyError(perm)
    return role in PERMISSIONS[perm]


def highest_role(roles: list[str]) -> str | None:
    """The most privileged of the given system roles (unknown names ignored)."""
    known = [r for r in roles if r in ROLE_RANK]
    return max(known, key=lambda r: ROLE_RANK[r]) if known else None
