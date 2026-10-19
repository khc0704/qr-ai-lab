import { describe, expect, it } from "vitest";
import { ASSIGNABLE_ROLES, SYSTEM_ROLES, can, canCancelJob, canProject, isAdminRole, projectRole } from "@/lib/roles";
import type { Project, User } from "@/types/domain";

const user = (id: number, role: User["role"] = "user"): Pick<User, "id" | "role"> => ({ id, role });
const project = (members: [number, Project["members"][number]["role"]][]): Pick<Project, "members"> => ({
  members: members.map(([id, role]) => ({
    user: { id, username: `u${id}`, email: "", displayName: `u${id}`, role: "user", isActive: true },
    role,
    addedAt: "",
  })),
});

describe("projectRole", () => {
  const p = project([
    [1, "owner"],
    [2, "maintainer"],
    [3, "member"],
    [4, "viewer"],
  ]);
  it("returns the membership role", () => {
    expect(projectRole(p, user(1))).toBe("owner");
    expect(projectRole(p, user(3))).toBe("member");
    expect(projectRole(p, user(4))).toBe("viewer");
  });
  it("is null for non-members and anonymous", () => {
    expect(projectRole(p, user(9))).toBeNull();
    expect(projectRole(p, null)).toBeNull();
    expect(projectRole(undefined, user(1))).toBeNull();
  });
  it("treats system admins as owner everywhere (backend project_access)", () => {
    expect(projectRole(p, user(9, "admin"))).toBe("owner");
    expect(projectRole(undefined, user(9, "superadmin"))).toBe("owner");
  });
});

describe("canProject", () => {
  it("matches the backend minimum role per endpoint", () => {
    expect(canProject("viewer", "view")).toBe(true);
    expect(canProject("viewer", "run")).toBe(false);
    expect(canProject("viewer", "edit")).toBe(false);
    expect(canProject("member", "run")).toBe(true);
    expect(canProject("member", "edit")).toBe(true);
    expect(canProject("member", "manage")).toBe(false);
    expect(canProject("maintainer", "manage")).toBe(true);
    expect(canProject("maintainer", "settings")).toBe(false);
    expect(canProject("owner", "settings")).toBe(true);
  });
  it("denies without a role", () => {
    expect(canProject(null, "view")).toBe(false);
    expect(canProject(undefined, "run")).toBe(false);
  });
});

describe("canCancelJob", () => {
  it("lets members cancel only their own jobs and maintainers any job", () => {
    expect(canCancelJob("member", user(3), 3)).toBe(true);
    expect(canCancelJob("member", user(3), 2)).toBe(false);
    expect(canCancelJob("maintainer", user(2), 3)).toBe(true);
    expect(canCancelJob("owner", user(1), 3)).toBe(true);
    expect(canCancelJob("viewer", user(4), 4)).toBe(false);
    expect(canCancelJob(null, user(4), 4)).toBe(false);
  });
});

describe("system permissions", () => {
  it("isAdminRole / can", () => {
    expect(isAdminRole("admin")).toBe(true);
    expect(isAdminRole("superadmin")).toBe(true);
    expect(isAdminRole("user")).toBe(false);
    expect(can({ permissions: ["jobs.control"] }, "jobs.control")).toBe(true);
    expect(can({ permissions: ["jobs.control"] }, "pool.manage")).toBe(false);
    expect(can(null, "admin.view")).toBe(false);
  });
});

describe("system roles", () => {
  it("the UI can assign at most admin: superadmin is fixed by the backend's SUPERADMIN_USERNAME", () => {
    expect(SYSTEM_ROLES).toEqual(["superadmin", "admin", "user"]);
    expect(ASSIGNABLE_ROLES).toEqual(["admin", "user"]);
    expect(ASSIGNABLE_ROLES).not.toContain("superadmin");
  });
});
