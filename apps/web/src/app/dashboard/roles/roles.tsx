"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, LoaderCircle, Lock, Plus, Search, ShieldCheck, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/http";
import {
  createRole,
  deleteRole,
  getMyRoles,
  isSystemRoleName,
  listPermissions,
  listRoles,
  roleDisplayName,
  updateRole,
  type PermissionModule,
  type RoleSummary,
} from "@/lib/api/identity-api";
import { cn } from "@/lib/utils";
import { ListSkeleton } from "@/components/ui/page-skeletons";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; roles: RoleSummary[]; canManage: boolean };

type Notice = { tone: "success" | "error"; text: string };

const NAME_PATTERN = /^[a-z0-9_-]+$/;

function RoleListSkeleton() {
  return <ListSkeleton rows={4} />;
}

function permissionSummary(permissions: string[]): string {
  if (permissions.includes("*")) return "All permissions";
  const count = permissions.length;
  return `${count} ${count === 1 ? "permission" : "permissions"}`;
}

export default function RolesClient() {
  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [catalog, setCatalog] = useState<PermissionModule[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [roles, modules, myRoles] = await Promise.all([
        listRoles(),
        listPermissions(),
        getMyRoles(),
      ]);
      setCatalog(modules);
      setStatus({
        state: "ready",
        roles,
        canManage:
          myRoles.permissions.includes("roles:write") ||
          myRoles.permissions.includes("*"),
      });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load roles.";
      setStatus({ state: "error", message });
    }
  }, []);

  const refreshRoles = useCallback(async () => {
    try {
      const roles = await listRoles();
      setStatus((current) => (current.state === "ready" ? { ...current, roles } : current));
    } catch {
      await load();
    }
  }, [load]);

  useEffect(() => {
    void load();
  }, [load]);

  const editingRole =
    status.state === "ready" && editingId
      ? (status.roles.find((role) => role.id === editingId) ?? null)
      : null;

  const readOnly =
    status.state !== "ready" || !status.canManage || editingRole?.isSystemRole === true;

  const filteredModules = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return catalog;
    return catalog
      .map((module) => {
        if (module.label.toLowerCase().includes(term)) return module;
        const matching = module.permissions.filter(
          (permission) =>
            permission.key.toLowerCase().includes(term) ||
            permission.description.toLowerCase().includes(term),
        );
        return matching.length > 0 ? { ...module, permissions: matching } : null;
      })
      .filter((module): module is PermissionModule => module !== null);
  }, [catalog, query]);

  const totalPermissions = useMemo(
    () => catalog.reduce((total, module) => total + module.permissions.length, 0),
    [catalog],
  );

  function startCreate() {
    setEditingId(null);
    setName("");
    setNameError(null);
    setSelected(new Set());
    setQuery("");
    setNotice(null);
  }

  function selectRole(role: RoleSummary) {
    setEditingId(role.id);
    setName(role.name);
    setNameError(null);
    setSelected(new Set(role.permissions));
    setQuery("");
    setNotice(null);
  }

  function togglePermission(key: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function toggleModule(module: PermissionModule) {
    const keys = module.permissions.map((permission) => permission.key);
    setSelected((current) => {
      const next = new Set(current);
      const allSelected = keys.every((key) => next.has(key));
      if (allSelected) {
        keys.forEach((key) => next.delete(key));
      } else {
        keys.forEach((key) => next.add(key));
      }
      return next;
    });
  }

  async function onSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readOnly || saving) return;

    const trimmed = name.trim();
    if (!trimmed) return;
    if (!NAME_PATTERN.test(trimmed)) {
      setNameError("Use lowercase letters, numbers, hyphens, or underscores.");
      return;
    }
    if (isSystemRoleName(trimmed)) {
      setNameError("That name is reserved for a system role.");
      return;
    }

    const permissionKeys = [...selected];
    setSaving(true);
    setNotice(null);
    try {
      if (editingRole) {
        await updateRole(editingRole.id, { name: trimmed, permissionKeys });
      } else {
        await createRole({ name: trimmed, permissionKeys });
      }
      await refreshRoles();
      startCreate();
      setNotice({ tone: "success", text: `Role "${trimmed}" saved.` });
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not save the role.",
      });
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!editingRole || readOnly || saving) return;
    setSaving(true);
    setNotice(null);
    try {
      await deleteRole(editingRole.id);
      await refreshRoles();
      setConfirmOpen(false);
      startCreate();
      setNotice({ tone: "success", text: `Role "${editingRole.name}" deleted.` });
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not delete the role.",
      });
      setConfirmOpen(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-hidden">
      <PageHeader
        title="Roles & permissions"
        description="Create custom roles with precise permissions and manage who has them."
        icon={ShieldCheck}
      />

      <div className="grid min-h-0 flex-1 gap-6 [grid-auto-rows:minmax(0,1fr)] lg:grid-cols-[19rem_minmax(0,1fr)]">
        <section className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card">
          <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3.5">
            <h2 className="flex items-center gap-2 font-display text-sm font-semibold text-foreground">
              <ShieldCheck aria-hidden="true" className="size-4 text-primary" />
              Roles
            </h2>
            {status.state === "ready" ? (
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground tabular-nums">
                  {status.roles.length}
                </span>
                {status.canManage ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="icon-sm"
                    aria-label="New role"
                    title="New role"
                    onClick={startCreate}
                  >
                    <Plus aria-hidden="true" />
                  </Button>
                ) : null}
              </div>
            ) : null}
          </header>

            <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-3">
            {status.state === "loading" ? <RoleListSkeleton /> : null}

            {status.state === "error" ? (
              <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
                <p className="text-sm font-medium text-destructive">{status.message}</p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={() => void load()}
                >
                  Try again
                </Button>
              </div>
            ) : null}

            {status.state === "ready" ? (
              <ul className="space-y-1">
                {status.roles.map((role) => {
                  const isSelected = editingId === role.id;
                  return (
                    <li
                      key={role.id}
                      className={cn(
                        "flex items-center rounded-lg transition-colors",
                        isSelected && "bg-primary/5 ring-1 ring-primary/30",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => selectRole(role)}
                        aria-pressed={isSelected}
                        className="min-w-0 flex-1 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-muted/60"
                      >
                        <span className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-foreground">
                            {roleDisplayName(role.name)}
                          </span>
                          {role.isSystemRole ? (
                            <Badge variant="secondary" className="shrink-0">
                              System
                            </Badge>
                          ) : null}
                        </span>
                        <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                          {permissionSummary(role.permissions)}
                        </span>
                      </button>
                      {status.canManage && !role.isSystemRole ? (
                        <button
                          type="button"
                          onClick={() => {
                            selectRole(role);
                            setConfirmOpen(true);
                          }}
                          aria-label={`Delete role ${roleDisplayName(role.name)}`}
                          title="Delete role"
                          className="mr-1 flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                        >
                          <Trash2 aria-hidden="true" className="size-3.5" />
                        </button>
                      ) : null}
                    </li>
                  );
                })}
                {status.roles.length === 0 ? (
                  <li className="px-3 py-8 text-center text-xs text-muted-foreground">
                    No custom roles yet. Create one to grant a precise set of permissions.
                  </li>
                ) : null}
              </ul>
            ) : null}
          </div>
        </section>

        <section className="flex min-w-0 min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card">
          <form
            id="role-builder-form"
            onSubmit={(event) => void onSave(event)}
            className="flex min-w-0 min-h-0 flex-1 flex-col"
          >
            <div className="border-b border-border px-5 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-display text-sm font-semibold text-foreground">
                  {editingRole
                    ? `Edit ${roleDisplayName(editingRole.name)}`
                    : "Create a custom role"}
                </h2>
                {editingRole?.isSystemRole ? (
                  <Badge variant="secondary">System</Badge>
                ) : editingRole ? (
                  <Badge variant="outline">Custom</Badge>
                ) : null}
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="role-name">Role name</Label>
                  <Input
                    id="role-name"
                    value={name}
                    onChange={(event) => {
                      setName(event.target.value);
                      setNameError(null);
                    }}
                    disabled={readOnly}
                    placeholder="e.g. finance_viewer"
                    aria-invalid={nameError ? true : undefined}
                  />
                  <p className="text-xs text-muted-foreground">
                    Use lowercase letters, numbers, hyphens, or underscores.
                  </p>
                  {nameError ? (
                    <p role="alert" className="text-sm font-medium text-destructive">
                      {nameError}
                    </p>
                  ) : null}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="permission-search">Permissions</Label>
                  <div className="relative">
                    <Search
                      aria-hidden="true"
                      className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
                    />
                    <Input
                      id="permission-search"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      disabled={readOnly}
                      className="pl-8"
                      placeholder="Search permissions"
                    />
                  </div>
                </div>
              </div>

              {readOnly ? (
                <div className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                  <Lock aria-hidden="true" className="size-3.5 shrink-0" />
                  {editingRole?.isSystemRole
                    ? "System roles are built in and cannot be changed."
                    : "You have read-only access. Ask an owner or admin to make changes."}
                </div>
              ) : null}

              {notice ? (
                <div
                  role={notice.tone === "error" ? "alert" : "status"}
                  className={cn(
                    "mt-3 rounded-lg border px-3 py-2 text-sm font-medium",
                    notice.tone === "error"
                      ? "border-destructive/40 bg-destructive/5 text-destructive"
                      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
                  )}
                >
                  {notice.text}
                </div>
              ) : null}
            </div>

          <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-3">
              {status.state === "loading" ? <ListSkeleton rows={3} /> : null}

              {status.state === "ready" && filteredModules.length === 0 ? (
                <div className="px-4 py-10 text-center text-sm text-muted-foreground">
                  {query.trim() ? "No permissions match your search." : "No permissions available."}
                </div>
              ) : null}

              {status.state === "ready" && filteredModules.length > 0 ? (
                <div className="space-y-3">
                  {filteredModules.map((module) => {
                    const keys = module.permissions.map((permission) => permission.key);
                    const allSelected = keys.every((key) => selected.has(key));
                    const someSelected = keys.some((key) => selected.has(key));
                    return (
                      <div key={module.key} className="relative overflow-hidden rounded-lg border border-border">
                        <div className="flex items-center gap-2.5 bg-muted/40 px-3 py-2">
                          <Checkbox
                            id={`module-${module.key}`}
                            checked={allSelected ? true : someSelected ? "indeterminate" : false}
                            onCheckedChange={() => toggleModule(module)}
                            disabled={readOnly}
                            aria-label={`Select all ${module.label} permissions`}
                          />
                          <label
                            htmlFor={`module-${module.key}`}
                            className="min-w-0 flex-1 cursor-pointer text-sm font-medium text-foreground"
                          >
                            {module.label}
                          </label>
                          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                            {module.permissions.length}
                          </span>
                        </div>
                        <ul className="divide-y divide-border border-t border-border">
                          {module.permissions.map((permission) => (
                            <li key={permission.key} className="flex items-start gap-2.5 px-3 py-2">
                              <Checkbox
                                id={`permission-${permission.key}`}
                                checked={selected.has(permission.key)}
                                onCheckedChange={() => togglePermission(permission.key)}
                                disabled={readOnly}
                                aria-label={permission.description}
                              />
                              <label
                                htmlFor={`permission-${permission.key}`}
                                className="min-w-0 flex-1 cursor-pointer"
                              >
                                <span className="block truncate font-mono text-xs text-foreground">
                                  {permission.key}
                                </span>
                                <span className="block text-xs text-muted-foreground">
                                  {permission.description}
                                </span>
                              </label>
                            </li>
                          ))}
                        </ul>
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>
          </form>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-muted/30 px-4 py-3">
            <p className="text-xs text-muted-foreground">
              <span className="font-medium text-foreground tabular-nums">{selected.size}</span> of{" "}
              <span className="tabular-nums">{totalPermissions}</span> permissions selected
            </p>
            <div className="flex items-center gap-2">
              {editingRole && !readOnly ? (
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  onClick={() => setConfirmOpen(true)}
                  disabled={saving}
                >
                  <Trash2 aria-hidden="true" className="size-3.5" />
                  Delete
                </Button>
              ) : null}
              {editingRole ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={startCreate}
                  disabled={saving}
                >
                  Cancel
                </Button>
              ) : null}
              <Button
                type="submit"
                form="role-builder-form"
                size="sm"
                disabled={readOnly || saving || selected.size === 0 || !name.trim()}
              >
                {saving ? (
                  <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                ) : editingRole ? (
                  <Check aria-hidden="true" className="size-4" />
                ) : (
                  <Plus aria-hidden="true" className="size-4" />
                )}
                {editingRole ? "Save changes" : "Create role"}
              </Button>
            </div>
          </div>
        </section>
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete role?</DialogTitle>
            <DialogDescription>
              {editingRole
                ? `Role "${roleDisplayName(editingRole.name)}" will be removed and its grants revoked. This cannot be undone.`
                : "This role will be removed. This cannot be undone."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void onDelete()}
              disabled={saving}
            >
              {saving ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
