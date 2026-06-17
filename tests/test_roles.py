"""Tests for app.roles — scoped role + permission model below admin."""
import json
import os
import unittest

from app import roles


OWNER = "owner@khawarsons.com"
ADMIN = "admin1@khawarsons.com"
REGIONAL = "reg@khawarsons.com"
FUEL = "fuel@khawarsons.com"
VIEWER = "clerk@khawarsons.com"


class RolesTestBase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("OPS_OWNER_EMAIL", "OPS_ADMIN_EMAILS", "OPS_ROLES")}
        os.environ["OPS_OWNER_EMAIL"] = OWNER
        os.environ["OPS_ADMIN_EMAILS"] = f"{OWNER},{ADMIN}"
        os.environ["OPS_ROLES"] = json.dumps([
            {"email": REGIONAL, "role": "regional_manager", "sites": ["4", "11"]},
            {"email": FUEL, "role": "fuel_manager"},
        ])
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestRoleOf(RolesTestBase):
    def test_owner_admin_scoped_default(self):
        self.assertEqual(roles.role_of(OWNER), "owner")
        self.assertEqual(roles.role_of(ADMIN), "admin")
        self.assertEqual(roles.role_of(REGIONAL), "regional_manager")
        self.assertEqual(roles.role_of(FUEL), "fuel_manager")
        self.assertEqual(roles.role_of(VIEWER), "viewer")
        self.assertEqual(roles.role_of(""), "viewer")

    def test_owner_cannot_be_demoted_by_ops_roles(self):
        os.environ["OPS_ROLES"] = json.dumps([{"email": OWNER, "role": "viewer"}])
        self.assertEqual(roles.role_of(OWNER), "owner")

    def test_case_insensitive(self):
        self.assertEqual(roles.role_of(OWNER.upper()), "owner")


class TestPermissions(RolesTestBase):
    def test_admin_can_mutate(self):
        self.assertTrue(roles.can(ADMIN, roles.CLOSE_TASK))
        self.assertTrue(roles.can(ADMIN, roles.ASSIGN_TASK))

    def test_viewer_is_read_only(self):
        self.assertTrue(roles.can(VIEWER, roles.VIEW))
        self.assertFalse(roles.can(VIEWER, roles.CLOSE_TASK))

    def test_fuel_manager_scope_of_powers(self):
        self.assertTrue(roles.can(FUEL, roles.VIEW_FUEL))
        self.assertFalse(roles.can(FUEL, roles.CLOSE_TASK))

    def test_regional_manager_can_act(self):
        self.assertTrue(roles.can(REGIONAL, roles.CLOSE_TASK))

    def test_owner_only_manage_roles(self):
        self.assertTrue(roles.can(OWNER, roles.MANAGE_ROLES))
        self.assertFalse(roles.can(ADMIN, roles.MANAGE_ROLES))


class TestSiteScope(RolesTestBase):
    def test_owner_admin_all_stores(self):
        self.assertIsNone(roles.site_scope(OWNER))
        self.assertIsNone(roles.site_scope(ADMIN))

    def test_regional_manager_limited(self):
        self.assertEqual(roles.site_scope(REGIONAL), {"4", "11"})

    def test_fuel_manager_all_stores(self):
        # fuel_manager isn't a per-store-scoped role -> sees all stores.
        self.assertIsNone(roles.site_scope(FUEL))

    def test_can_view_site_by_number_and_alias(self):
        self.assertTrue(roles.can_view_site(REGIONAL, "4 Channelview"))
        self.assertTrue(roles.can_view_site(REGIONAL, "Windchase"))   # alias of 11
        self.assertFalse(roles.can_view_site(REGIONAL, "9 Bissonnet"))

    def test_owner_views_any_site(self):
        self.assertTrue(roles.can_view_site(OWNER, "9 Bissonnet"))


class TestCanActOnSite(RolesTestBase):
    def test_regional_manager_in_scope(self):
        self.assertTrue(roles.can_act_on_site(REGIONAL, "4 Channelview", roles.CLOSE_TASK))

    def test_regional_manager_out_of_scope(self):
        self.assertFalse(roles.can_act_on_site(REGIONAL, "9 Bissonnet", roles.CLOSE_TASK))

    def test_viewer_cannot_act_even_in_scope(self):
        self.assertFalse(roles.can_act_on_site(VIEWER, "4 Channelview", roles.CLOSE_TASK))


class TestRobustness(RolesTestBase):
    def test_bad_ops_roles_env_does_not_crash(self):
        os.environ["OPS_ROLES"] = "{not valid json"
        self.assertEqual(roles.role_of(REGIONAL), "viewer")  # falls back cleanly
        self.assertTrue(roles.can(OWNER, roles.VIEW))

    def test_unknown_role_ignored(self):
        os.environ["OPS_ROLES"] = json.dumps([{"email": "x@k.com", "role": "wizard"}])
        self.assertEqual(roles.role_of("x@k.com"), "viewer")

    def test_backcompat_helpers(self):
        self.assertTrue(roles.is_owner(OWNER))
        self.assertTrue(roles.is_admin(ADMIN))
        self.assertFalse(roles.is_admin(VIEWER))


if __name__ == "__main__":
    unittest.main()
