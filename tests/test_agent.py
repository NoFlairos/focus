"""Regression checks for Focus Ratio's local accounting and window matching."""

import datetime as dt
import importlib.util
import pathlib
import tempfile
import time
import unittest
from unittest import mock


AGENT_PATH = pathlib.Path(__file__).resolve().parents[1] / "agent" / "focus_ratio_agent.py"
spec = importlib.util.spec_from_file_location("focus_ratio_agent", AGENT_PATH)
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)
ORIGINAL_VISIBLE_CLIENTS = agent.visible_clients
ORIGINAL_IN_WORK_HOURS = agent.in_work_hours


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = pathlib.Path(self.temp.name)
        self.paths = mock.patch.multiple(
            agent,
            CONFIG_DIR=root / "config",
            STATE_DIR=root / "state",
            CONFIG_PATH=root / "config" / "config.json",
            STATE_PATH=root / "state" / "state.json",
            DB_PATH=root / "state" / "history.sqlite3",
            SOCKET_PATH=root / "state" / "control.sock",
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.clients = [{"app_id": "Test", "window_title": "Test", "address": "0x123"}]
        self.visible = mock.patch.object(agent, "visible_clients", lambda: self.clients)
        self.focus = mock.patch.object(agent, "focused_window_address", lambda: "0x123")
        self.session = mock.patch.object(agent, "session_status", lambda: (False, False))
        self.schedule = mock.patch.object(agent, "in_work_hours", lambda now, schedule: True)
        self.hypr = mock.patch.object(agent, "hypr_json", return_value=[])
        # Never show real desktop notifications from tests.
        self.popen = mock.patch.object(agent.subprocess, "Popen")
        for patcher in (self.visible, self.focus, self.session, self.schedule, self.hypr, self.popen):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runtime = agent.Runtime()
        self.addCleanup(lambda: self.runtime.store.close())
        # Calendar days in tests; the late-night shift has its own test.
        self.runtime.config["day_start_hour"] = 0
        self.closed = []
        # Applies to every Runtime a test creates, including after simulated restarts.
        closer = mock.patch.object(agent.Runtime, "close_app_windows", lambda runtime, clients: self.closed.extend(clients))
        closer.start()
        self.addCleanup(closer.stop)

    def test_app_name_comes_from_desktop_metadata(self):
        data = pathlib.Path(self.temp.name) / "data" / "applications"
        data.mkdir(parents=True)
        (data / "sample.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Sample Editor\nStartupWMClass=odd.window.Class\n")
        agent.desktop_app_names.cache_clear()
        self.addCleanup(agent.desktop_app_names.cache_clear)
        with mock.patch.dict("os.environ", {"XDG_DATA_HOME": str(data.parent), "XDG_DATA_DIRS": ""}):
            self.assertEqual(agent.app_display_name("odd.window.Class"), "Sample Editor")
            self.assertEqual(agent.app_display_name("unknown.app"), "unknown.app")
            self.assertEqual(agent.target_display_name("app:odd.window.Class"), "Sample Editor")
            self.assertEqual(agent.target_display_name("app:chrome-x.com__-default"), "x.com")
            self.assertEqual(agent.target_display_name("app:chrome-youtube.com__-default"), "youtube.com")
            self.assertEqual(agent.target_display_name("app:odd.window.Class", "My App"), "My App")

    def test_site_names_preserve_service_identity(self):
        self.assertEqual(agent.target_display_name("site:console.cloud.google.com"), "console.cloud.google.com")
        self.assertEqual(agent.target_display_name("site:accounts.google.com"), "accounts.google.com")
        self.assertEqual(agent.target_display_name("site:unknown.google.com"), "unknown.google.com")
        self.assertEqual(agent.target_display_name("site:preview-one.pages.dev"), "preview-one.pages.dev")
        self.assertEqual(agent.target_display_name("site:preview-two.pages.dev"), "preview-two.pages.dev")
        self.assertEqual(agent.target_display_name("site:example.co.uk"), "example.co.uk")
        self.assertEqual(agent.target_display_name("site:example.com", "My workspace"), "My workspace")

    def test_browser_site_requires_matching_browser_window(self):
        windows = [{"title": "A post", "domain": "x.com"}]
        unrelated = [{"app_id": "foot", "window_title": "A post", "address": "0x999"}]
        self.assertEqual(self.runtime.visible_sites(unrelated, windows), [])
        browser = [{"app_id": "chromium", "window_title": "A post - Chromium", "address": "0x456"}]
        self.assertEqual(self.runtime.visible_sites(browser, windows), [
            {"target_id": "site:x.com", "name": "x.com", "address": "0x456"}
        ])
        self.assertEqual(self.runtime.visible_sites(browser, [{"title": "A post", "domain": "sub.x.com"}])[0]["target_id"], "site:sub.x.com")
        self.assertEqual(self.runtime.visible_sites(browser, [{"title": "", "domain": "x.com"}]), [])

    def test_google_parent_does_not_capture_gmail_or_cloud(self):
        clients = [{"app_id": "chromium", "window_title": "Inbox - Chromium", "address": "0x123"}]
        for domain in ("mail.google.com", "console.cloud.google.com", "google.com"):
            sites = self.runtime.visible_sites(clients, [{"title": "Inbox", "domain": domain}])
            self.assertEqual(sites[0]["target_id"], "site:" + domain)
        self.assertEqual(agent.service_site_for_app("chrome-mail.google.com__-default"), "site:mail.google.com")

    def test_manual_merge_shares_usage_and_preserves_destination_settings(self):
        for target in ("site:first.example", "app:test"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": "app:test", "quota_minutes": 7})
        now = dt.datetime.now().astimezone()
        bucket = agent.current_hour_bucket(now)
        self.runtime.store.add_times({"site:first.example": "consumption"}, 20, bucket, now.date().isoformat())
        self.assertTrue(self.runtime.handle_message({"op": "merge", "source": "site:first.example", "destination": "app:test"})["ok"])
        self.clients.append({"app_id": "google-chrome", "window_title": "Inbox - Google Chrome", "address": "0x456"})
        self.runtime.browser_windows = {"1": {"title": "Inbox", "domain": "first.example"}}
        self.runtime.last_browser_snapshot = time.monotonic()
        self.runtime.tick(10)
        rows = self.runtime.latest_state["tracked"]
        self.assertEqual([row["id"] for row in rows], ["app:test"])
        self.assertEqual(rows[0]["used_seconds"], 30)
        self.assertEqual(rows[0]["quota_seconds"], 420)
        self.assertEqual(rows[0]["members"], ["app:test", "site:first.example"])
        self.assertFalse(self.runtime.handle_message({"op": "merge", "source": "site:first.example", "destination": "app:test"})["ok"])
        self.runtime.store.close()
        self.runtime = agent.Runtime()
        self.assertEqual(self.runtime.resolve_target_id("site:first.example"), "app:test")
        self.assertEqual(self.runtime.store.used_this_hour("app:test", bucket), 30)

    def test_group_merges_flatten_links_without_cycles(self):
        for target in ("app:a", "app:b", "site:c.example"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "neutral"})
        for source, destination in (("app:a", "app:b"), ("app:b", "site:c.example")):
            self.assertTrue(self.runtime.handle_message({"op": "merge", "source": source, "destination": destination})["ok"])
        self.assertEqual(self.runtime.resolve_target_id("app:a"), "site:c.example")
        self.assertEqual(self.runtime.resolve_target_id("app:b"), "site:c.example")
        self.assertEqual(set(self.runtime.config["targets"]), {"site:c.example"})

    def test_blocking_respects_pause_schedule_idle_and_visible_tabs(self):
        target = "site:example.org"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        now = dt.datetime.now().astimezone()
        self.runtime.store.add_times({target: "consumption"}, 601, agent.current_hour_bucket(now), now.date().isoformat())
        self.assertEqual(self.runtime.blocked_domains(), ["example.org"])
        self.runtime.paused = True
        self.assertEqual(self.runtime.blocked_domains(), [])
        self.runtime.paused = False
        with mock.patch.object(agent, "in_work_hours", return_value=False):
            self.assertEqual(self.runtime.blocked_domains(), [])
        with mock.patch.object(agent, "session_status", return_value=(False, True)):
            self.assertEqual(self.runtime.blocked_domains(), [])
        self.clients = [{"app_id": "google-chrome", "window_title": "Visible - Google Chrome", "address": "0x1"}]
        response = self.runtime.handle_message({"op": "browser_snapshot", "windows": [
            {"id": 1, "tab_id": 10, "title": "Visible", "domain": "example.org"},
            {"id": 2, "tab_id": 20, "title": "Elsewhere", "domain": "example.org"}]})
        self.assertEqual(response["blocked_tab_ids"], [10])

    def test_ambiguous_browser_titles_are_not_assigned(self):
        clients = [{"app_id": "chromium", "window_title": "Inbox - Chromium", "address": address}
                   for address in ("0x1", "0x2")]
        self.assertEqual(self.runtime.visible_sites(clients, [{"title": "Inbox", "domain": "example.org"}]), [])

    def test_diagnostics_detect_legacy_extension_without_tab_ids(self):
        self.clients = [{"app_id": "chromium", "window_title": "Inbox - Chromium", "address": "0x123"}]
        window = {"id": 1, "title": "Inbox", "domain": "example.org"}
        for windows, expected in (([window], False), ([{**window, "tab_id": 10}], True), ([], None)):
            with self.subTest(expected=expected):
                self.runtime.handle_message({"op": "browser_snapshot", "windows": windows})
                self.runtime.tick(0)
                diagnostics = self.runtime.latest_state["diagnostics"]
                self.assertTrue(diagnostics["browser_connected"])
                self.assertIs(diagnostics["browser_can_close_tabs"], expected)

    def test_merged_sites_share_blocking_and_browser_sessions_coexist(self):
        for target in ("site:first.example", "site:second.example"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "merge", "source": "site:first.example", "destination": "site:second.example"})
        now = dt.datetime.now().astimezone()
        self.runtime.store.add_times({"site:second.example": "consumption"}, 601,
                                     agent.current_hour_bucket(now), now.date().isoformat())
        self.assertEqual(self.runtime.blocked_domains(), ["first.example", "second.example"])
        for browser in ("chromium-session", "chrome-session"):
            self.runtime.handle_message({"op": "browser_snapshot", "browser_id": browser,
                                         "windows": [{"id": 1, "title": browser, "domain": "example.org"}]})
        self.assertEqual(len(self.runtime.browser_windows), 2)

    def test_legacy_parent_link_is_corrected_but_manual_links_survive(self):
        source = "app:chrome-service.example.org__-default"
        self.runtime.config.pop("link_schema", None)
        self.runtime.config["service_links"][source] = "site:example.org"
        agent.save_config(self.runtime.config)
        self.runtime.store.close()
        self.runtime = agent.Runtime()
        self.assertEqual(self.runtime.resolve_target_id(source), "site:service.example.org")
        self.runtime.config["service_links"][source] = "site:example.org"
        agent.save_config(self.runtime.config)
        self.runtime.store.close()
        self.runtime = agent.Runtime()
        self.assertEqual(self.runtime.resolve_target_id(source), "site:example.org")

    def test_unlink_web_app_stays_independent_after_restart(self):
        app = "app:chrome-example.org__-default"
        site = "site:example.org"
        self.runtime.handle_message({"op": "classify", "target_id": site, "category": "consumption"})
        self.runtime.reconcile_targets({app})
        self.assertEqual(self.runtime.resolve_target_id(app), site)
        self.assertTrue(self.runtime.handle_message({"op": "unlink", "target_id": app})["ok"])
        self.runtime.reconcile_targets({app})
        self.assertEqual(self.runtime.resolve_target_id(app), app)
        self.assertEqual(self.runtime.config["targets"][app]["quota_minutes"], 10)
        self.runtime.store.close()
        self.runtime = agent.Runtime()
        self.assertEqual(self.runtime.resolve_target_id(app), app)
        self.assertTrue(self.runtime.handle_message({"op": "merge", "source": app, "destination": site})["ok"])
        self.assertEqual(self.runtime.resolve_target_id(app), site)

    def test_detach_main_member_keeps_history_with_remaining_group(self):
        for target in ("app:a", "app:b", "site:example.org"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        for source in ("app:a", "app:b"):
            self.runtime.handle_message({"op": "merge", "source": source, "destination": "site:example.org"})
        now = dt.datetime.now().astimezone()
        bucket = agent.current_hour_bucket(now)
        self.runtime.store.add_times({"site:example.org": "consumption"}, 40, bucket, now.date().isoformat())
        self.assertTrue(self.runtime.handle_message({"op": "unlink", "target_id": "site:example.org"})["ok"])
        self.assertEqual(self.runtime.resolve_target_id("app:b"), "app:a")
        self.assertEqual(self.runtime.resolve_target_id("site:example.org"), "site:example.org")
        self.assertEqual(self.runtime.store.used_this_hour("app:a", bucket), 40)
        self.assertEqual(self.runtime.store.used_this_hour("site:example.org", bucket), 0)
        self.assertFalse(self.runtime.handle_message({"op": "unlink", "target_id": "site:example.org"})["ok"])
        self.assertFalse(self.runtime.handle_message({"op": "unlink", "target_id": "app:unknown"})["ok"])

    def test_timed_pause_survives_restart_and_resumes(self):
        self.assertTrue(self.runtime.handle_message({"op": "pause", "paused": True, "duration": "15"})["ok"])
        until = self.runtime.pause_until
        self.assertTrue(self.runtime.paused)
        self.runtime.store.close()
        self.runtime = agent.Runtime()
        self.assertTrue(self.runtime.paused)
        self.runtime.resume_if_due(dt.datetime.fromtimestamp(until + 1).astimezone())
        self.assertFalse(self.runtime.paused)
        self.assertFalse(agent.load_config()["pause_state"]["active"])
        self.assertFalse(self.runtime.handle_message({"op": "pause", "paused": True, "duration": "invalid"})["ok"])

    def test_warning_once_and_can_be_disabled(self):
        self.runtime.handle_message({"op": "classify", "target_id": "app:test", "category": "consumption"})
        with mock.patch.object(agent.subprocess, "Popen") as notify:
            self.runtime.tick(481)
            self.runtime.tick(1)
            self.assertEqual(notify.call_count, 1)
            self.assertIn("Limit approaching", notify.call_args.args[0][-2])
        self.runtime.handle_message({"op": "set_warning", "enabled": False})
        self.runtime.warned_limits.clear()
        with mock.patch.object(agent.subprocess, "Popen") as notify:
            self.runtime.tick(1)
            notify.assert_not_called()

    def test_weekly_summary_keeps_missing_data_unknown(self):
        today = dt.date(2026, 9, 29)
        history = [{"day": "2026-09-29", "screen_seconds": 600, "productive": 5},
                   {"day": "2026-09-23", "screen_seconds": 300, "neutral": 2},
                   {"day": "2026-09-22", "screen_seconds": 400, "consumption": 3},
                   {"day": "2026-09-15", "screen_seconds": 9999}]
        weekly = agent.Runtime.weekly_summary(history, today)
        self.assertEqual(weekly["current"]["screen_seconds"], 900)
        self.assertEqual(weekly["previous"]["screen_seconds"], 400)
        self.assertEqual(weekly["screen_delta"], 500)
        self.assertEqual(weekly["current"]["recorded_days"], 2)
        self.assertIsNone(agent.Runtime.weekly_summary(history[:1], today)["screen_delta"])

    def test_suggestions_are_optional_and_dismissible(self):
        for target in ("site:a.example", "site:b.example"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "productive"})
            self.runtime.config["site_names"][target[5:]] = "Same Service"
        self.runtime.tick(0)
        suggestions = self.runtime.latest_state["suggestions"]
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(len(self.runtime.config["targets"]), 2)
        self.runtime.handle_message({"op": "dismiss_suggestion", **suggestions[0]})
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["suggestions"], [])

    def test_data_export_backup_and_confirmed_clear(self):
        self.runtime.handle_message({"op": "classify", "target_id": "app:test", "category": "consumption"})
        self.runtime.tick(12)
        response = self.runtime.handle_message({"op": "export_history"})
        self.assertTrue(response["ok"])
        exported = pathlib.Path(response["path"])
        self.assertIn("app:test,consumption,12", exported.read_text())
        self.assertIn("screen_time", exported.read_text())
        self.assertEqual(exported.stat().st_mode & 0o777, 0o600)
        response = self.runtime.handle_message({"op": "backup_settings"})
        self.assertIn("app:test", pathlib.Path(response["path"]).read_text())
        self.assertFalse(self.runtime.handle_message({"op": "clear_history"})["ok"])
        self.assertTrue(self.runtime.store.history())
        self.assertTrue(self.runtime.handle_message({"op": "clear_history", "confirm": True})["ok"])
        self.assertEqual(self.runtime.store.history(), [])
        self.assertIn("app:test", self.runtime.config["targets"])
        self.assertTrue(exported.exists())

    def consume(self, target, seconds, category="consumption"):
        now = dt.datetime.now().astimezone()
        self.runtime.store.add_times({target: category}, seconds, agent.current_hour_bucket(now), now.date().isoformat())

    def test_daily_limit_uses_todays_consumption(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.assertTrue(self.runtime.handle_message({"op": "set_limit_period", "target_id": target, "period": "day"})["ok"])
        self.assertEqual(self.runtime.config["targets"][target]["quota_minutes"], 60)
        self.assertTrue(self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 300})["ok"])
        self.assertEqual(self.runtime.config["targets"][target]["quota_minutes"], 300)
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        self.runtime.store.add_times({target: "consumption"}, 3600, "old", yesterday)
        self.consume(target, 300 * 60 - 5)
        self.runtime.tick(1)
        row = self.runtime.latest_state["tracked"][0]
        self.assertEqual((row["limit_period"], row["remaining_seconds"]), ("day", 4))
        self.assertEqual(self.closed, [])
        self.runtime.tick(5)
        self.assertEqual(len(self.closed), 1)
        self.assertFalse(self.runtime.handle_message({"op": "set_limit_period", "target_id": target, "period": "week"})["ok"])

    def test_snooze_grants_five_minutes_once_per_period(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 1})
        self.assertFalse(self.runtime.handle_message({"op": "snooze", "target_id": "app:unknown"})["ok"])
        self.runtime.tick(61)
        self.assertTrue(self.runtime.latest_state["tracked"][0]["can_snooze"])
        self.assertEqual(len(self.closed), 1)
        self.assertTrue(self.runtime.handle_message({"op": "snooze", "target_id": target})["ok"])
        self.assertFalse(self.runtime.handle_message({"op": "snooze", "target_id": target})["ok"])
        self.runtime.tick(1)
        row = self.runtime.latest_state["tracked"][0]
        self.assertEqual(row["remaining_seconds"], agent.SNOOZE_SECONDS - 2)
        self.assertFalse(row["can_snooze"])
        self.assertEqual(len(self.closed), 1)

    def test_limit_notification_offers_snooze_and_runs_it(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 1})
        process = mock.Mock()
        process.communicate.return_value = ("snooze\n", "")
        threads = []
        with mock.patch.object(agent.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.object(agent.threading, "Thread", side_effect=lambda target, daemon: threads.append(target) or mock.Mock()):
            self.runtime.tick(61)
        command = popen.call_args.args[0]
        self.assertIn("Test closed.", command)
        self.assertEqual(command[-2:], ["-A", "snooze=5 more minutes"])
        threads[-1]()
        self.assertEqual(self.runtime.config["snoozes"][target], agent.current_hour_bucket(dt.datetime.now().astimezone()))

    def test_limit_prompt_offers_snooze_briefly_after_closing(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 1})
        self.runtime.tick(61)
        command = agent.subprocess.Popen.call_args.args[0]
        self.assertIn("critical", command)
        self.clients = []
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["limit_prompts"], [{"id": target, "name": "Test"}])
        self.runtime.limit_prompts[target] -= agent.LIMIT_PROMPT_SECONDS
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["limit_prompts"], [])
        self.runtime.limit_prompts[target] = time.monotonic()
        self.runtime.handle_message({"op": "snooze", "target_id": target})
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["limit_prompts"], [])

    def test_day_start_hour_moves_late_night_to_previous_day(self):
        self.assertFalse(self.runtime.handle_message({"op": "set_day_start", "hour": 9})["ok"])
        self.assertTrue(self.runtime.handle_message({"op": "set_day_start", "hour": 4})["ok"])
        late = dt.datetime(2026, 10, 14, 2, 30).astimezone()
        self.assertEqual(self.runtime.tracking_date(late), dt.date(2026, 10, 13))
        self.assertEqual(self.runtime.tracking_date(late.replace(hour=4)), dt.date(2026, 10, 14))
        target = {"category": "consumption", "limit_period": "day", "quota_minutes": 30}
        self.runtime.store.add_times({"app:test": "consumption"}, 600, "old", "2026-10-13")
        status = self.runtime.limit_status("app:test", target, late)
        self.assertEqual((status["used"], status["period_key"]), (600, "day:2026-10-13"))

    def test_day_details_list_top_entries_per_day(self):
        self.consume("app:test", 600, "productive")
        self.consume("app:test", 60, "neutral")
        self.consume("site:video.example", 900)
        self.clients = []
        self.runtime.tick(0)
        details = self.runtime.latest_state["day_details"][dt.date.today().isoformat()]
        self.assertEqual([(row["id"], row["category"], row["seconds"]) for row in details],
                         [("site:video.example", "consumption", 900), ("app:test", "productive", 660)])

    def test_limit_suggestions_for_heavy_unlimited_entries(self):
        for target, category in (("app:heavy", "neutral"), ("app:light", "neutral"), ("app:work", "productive"),
                                 ("app:chromium", "neutral")):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": category})
            self.consume(target, 4 * 3600 if target != "app:light" else 3600, category)
        self.runtime.handle_message({"op": "classify", "target_id": "app:video", "category": "consumption"})
        self.runtime.handle_message({"op": "set_limit_action", "target_id": "app:video", "action": "keep_open"})
        self.consume("app:video", 7 * 3600)
        suggestions = self.runtime.limit_suggestions(dt.date.today())
        self.assertEqual([item["id"] for item in suggestions], ["app:video", "app:heavy"])
        self.assertEqual(suggestions[1]["daily_minutes"], 15)
        self.assertEqual(suggestions[0]["daily_minutes"], 45)
        self.assertTrue(self.runtime.handle_message({"op": "apply_limit_suggestion", "target_id": "app:video"})["ok"])
        video = self.runtime.config["targets"]["app:video"]
        self.assertEqual((video["limit_period"], video["quota_minutes"], video["limit_action"]), ("day", 45, "notify"))
        self.assertTrue(self.runtime.handle_message({"op": "dismiss_limit_suggestion", "target_id": "app:heavy"})["ok"])
        self.assertEqual(self.runtime.limit_suggestions(dt.date.today()), [])
        self.assertFalse(self.runtime.handle_message({"op": "apply_limit_suggestion", "target_id": "app:work"})["ok"])

    def test_focus_session_blocks_consumption_and_overrides_pause_and_schedule(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "pause", "paused": True, "duration": "manual"})
        self.assertFalse(self.runtime.handle_message({"op": "focus", "minutes": "10"})["ok"])
        self.assertTrue(self.runtime.handle_message({"op": "focus", "minutes": "25"})["ok"])
        self.assertFalse(self.runtime.paused)
        with mock.patch.object(agent, "in_work_hours", lambda now, schedule: False):
            self.runtime.tick(1)
        row = self.runtime.latest_state["tracked"][0]
        self.assertEqual((row["remaining_seconds"], row["limit_reason"], row["can_snooze"]), (0, "focus", False))
        self.assertEqual(len(self.closed), 1)
        self.assertTrue(self.runtime.latest_state["focus_until"])
        self.runtime.config["focus_session"]["until"] = time.time() - 1
        self.runtime.tick(1)
        self.assertIsNone(self.runtime.latest_state["focus_until"])
        self.assertEqual(self.runtime.config["focus_session"], {"until": None})

    def test_daily_budget_caps_all_consumption(self):
        for target in ("app:test", "app:other"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
            self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 60})
        self.assertFalse(self.runtime.handle_message({"op": "set_budget", "minutes": 9999})["ok"])
        self.assertTrue(self.runtime.handle_message({"op": "set_budget", "minutes": 30})["ok"])
        self.consume("app:other", 30 * 60)
        self.runtime.tick(1)
        row = next(row for row in self.runtime.latest_state["tracked"] if row["id"] == "app:test")
        self.assertEqual((row["remaining_seconds"], row["limit_reason"]), (0, "budget"))
        self.assertGreaterEqual(self.runtime.latest_state["budget_used_seconds"], 30 * 60)
        self.runtime.handle_message({"op": "set_budget", "minutes": 0})
        self.runtime.tick(0)
        row = next(row for row in self.runtime.latest_state["tracked"] if row["id"] == "app:test")
        self.assertEqual(row["limit_reason"], "limit")

    def test_weekly_report_once_per_week_with_comparison(self):
        today = dt.date.today()
        monday = today - dt.timedelta(days=today.weekday())
        with self.runtime.store.db:
            for offset, seconds in ((7, 7200), (14, 3600)):
                day = (monday - dt.timedelta(days=offset)).isoformat()
                self.runtime.store.db.execute("INSERT INTO daily_screen_time VALUES(?,?,?)", (day, seconds, day))
        self.runtime.config["last_weekly_summary"] = ""
        with mock.patch.object(self.runtime, "notify") as notify:
            self.runtime.weekly_report(dt.datetime.now().astimezone())
            self.runtime.weekly_report(dt.datetime.now().astimezone())
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1], "2h 00m screen time · 0m consumption · +1h 00m vs week before")
        self.runtime.config["last_weekly_summary"] = ""
        self.runtime.handle_message({"op": "set_weekly_summary", "enabled": False})
        with mock.patch.object(self.runtime, "notify") as notify:
            self.runtime.weekly_report(dt.datetime.now().astimezone())
        notify.assert_not_called()

    def test_config_pruning_keeps_known_entries_only(self):
        self.runtime.handle_message({"op": "classify", "target_id": "site:kept.example", "category": "neutral"})
        self.runtime.config["site_identity"] = {"kept.example": {}, "gone.example": {}}
        self.runtime.config["site_names"] = {"kept.example": "Kept", "gone.example": "Gone"}
        self.runtime.config["dismissed_suggestions"] = ["site:gone.example|site:kept.example"]
        self.runtime.config["independent_targets"] = ["site:gone.example", "site:kept.example"]
        self.runtime.prune_config()
        self.assertEqual(list(self.runtime.config["site_identity"]), ["kept.example"])
        self.assertEqual(self.runtime.config["site_names"], {"kept.example": "Kept"})
        self.assertEqual(self.runtime.config["dismissed_suggestions"], [])
        self.assertEqual(self.runtime.config["independent_targets"], ["site:kept.example"])

    def test_site_names_drop_parenthesised_asides(self):
        for raw, clean in (("X (formerly Twitter)", "X"), ("(3) Inbox", "Inbox"), ("Docs (Beta) - Editor", "Docs - Editor"),
                           ("(beta)", "(beta)"), ("Plain", "Plain")):
            self.assertEqual(agent.clean_site_name(raw), clean)
        self.runtime.config["site_names"]["x.com"] = "X (formerly Twitter)"
        self.runtime.handle_message({"op": "classify", "target_id": "site:x.com", "category": "consumption"})
        self.runtime.tick(0)
        self.assertEqual(next(r for r in self.runtime.latest_state["tracked"] if r["id"] == "site:x.com")["name"], "X")

    def test_state_has_labels_and_single_browser_status(self):
        self.runtime.handle_message({"op": "exclude", "target_id": "app:org.example.Mail"})
        self.runtime.tick(1)
        state = self.runtime.latest_state
        self.assertEqual(state["labels"]["app:org.example.Mail"], "Example Mail")
        self.assertEqual(state["labels"]["app:test"], "Test")
        self.assertIn(state["diagnostics"]["browser_status"], {"browser_closed", "connecting", "browser_offline"})

    def test_usage_writes_are_batched_and_flushed_on_close(self):
        import sqlite3
        store = self.runtime.store
        store.flush(force=True)
        self.consume("app:test", 30, "productive")
        other = sqlite3.connect(agent.DB_PATH)
        self.addCleanup(other.close)
        count = lambda: other.execute("SELECT COUNT(*) FROM daily_usage").fetchone()[0]
        self.assertEqual(count(), 0)
        self.assertEqual(store.target_today(dt.date.today().isoformat()), {"app:test": 30})
        store.last_commit -= agent.DB_COMMIT_SECONDS
        store.flush()
        self.assertEqual(count(), 1)
        self.consume("app:test", 5, "productive")
        store.close()
        self.assertEqual(other.execute("SELECT seconds FROM daily_usage").fetchone()[0], 35)
        self.runtime = agent.Runtime()

    def test_state_is_written_on_change_or_heartbeat_only(self):
        self.clients = []
        self.runtime.tick(0)
        agent.STATE_PATH.unlink()
        self.runtime.tick(0)
        self.assertFalse(agent.STATE_PATH.exists())
        self.runtime.written_at -= agent.STATE_HEARTBEAT_SECONDS
        self.runtime.tick(0)
        self.assertTrue(agent.STATE_PATH.exists())
        agent.STATE_PATH.unlink()
        self.clients = [{"app_id": "Test", "window_title": "Test", "address": "0x123"}]
        self.runtime.tick(1)
        self.assertTrue(agent.STATE_PATH.exists())

    def test_review_waits_for_ten_minutes_over_seven_days(self):
        now = dt.datetime.now().astimezone()
        bucket = agent.current_hour_bucket(now)
        self.clients = []
        old = (now.date() - dt.timedelta(days=agent.REVIEW_DAYS)).isoformat()
        self.runtime.store.add_times({"app:brief": "unclassified", "app:regular": "unclassified"}, 300, bucket, old)
        for offset in range(2):
            day = (now.date() - dt.timedelta(days=offset)).isoformat()
            self.runtime.store.add_times({"app:regular": "unclassified", "app:brief": "unclassified"},
                                         300 if offset else 299, bucket, day)
        self.runtime.tick(0)
        rows = {row["id"]: row for row in self.runtime.latest_state["tracked"]}
        self.assertEqual(list(rows), [])
        self.runtime.store.add_times({"app:regular": "unclassified"}, 1, bucket, now.date().isoformat())
        self.runtime.tick(0)
        rows = {row["id"]: row for row in self.runtime.latest_state["tracked"]}
        self.assertEqual(list(rows), ["app:regular"])
        self.assertTrue(rows["app:regular"]["review"])

    def test_smart_merges_same_site_unless_it_is_a_distinct_service(self):
        parent = "site:example.org"
        children = {"live": ("productive", {}), "music": ("neutral", {}),
                    "studio": ("productive", {"manifest": "https://studio.example.org/app.json"}),
                    "inbox": ("productive", {"application_name": "Inbox"})}
        self.runtime.handle_message({"op": "classify", "target_id": parent, "category": "productive"})
        self.runtime.config["site_identity"] = {"example.org": {"application_name": "", "manifest": ""},
                                                "docs.example.org": {"manifest": ""}}
        for name, (category, identity) in children.items():
            self.runtime.handle_message({"op": "classify", "target_id": "site:" + name + ".example.org", "category": category})
            self.runtime.config["site_identity"][name + ".example.org"] = identity
        self.runtime.link_sites(set())
        resolved = {name: self.runtime.resolve_target_id("site:" + name + ".example.org") for name in (*children, "docs")}
        self.assertEqual(resolved["live"], parent)
        self.assertEqual(resolved["docs"], parent)
        for name in ("music", "studio", "inbox"):
            self.assertEqual(resolved[name], "site:" + name + ".example.org")
        self.assertEqual(self.runtime.config["targets"][parent]["category"], "productive")
        self.assertNotIn("site:live.example.org", self.runtime.config["targets"])

    def test_smart_waits_for_identity_before_merging(self):
        self.runtime.handle_message({"op": "classify", "target_id": "site:example.org", "category": "productive"})
        self.runtime.link_sites({"new.example.org"})
        self.assertEqual(self.runtime.resolve_target_id("site:new.example.org"), "site:new.example.org")
        self.runtime.config["site_identity"]["new.example.org"] = {"manifest": "https://new.example.org/m.json"}
        self.runtime.link_sites(set())
        self.assertEqual(self.runtime.resolve_target_id("site:new.example.org"), "site:new.example.org")

    def test_pending_subdomains_share_one_review_entry_and_threshold(self):
        now = dt.datetime.now().astimezone()
        bucket, day = agent.current_hour_bucket(now), now.date().isoformat()
        self.clients = []
        for name in ("cloud", "live"):
            self.runtime.config["site_identity"][name + ".example.org"] = {"manifest": ""}
            self.runtime.store.add_times({"site:" + name + ".example.org": "unclassified"}, 300, bucket, day)
        self.runtime.config["site_identity"]["mail.example.org"] = {"manifest": "https://mail.example.org/m.json"}
        self.runtime.store.add_times({"site:mail.example.org": "unclassified"}, 900, bucket, day)
        self.runtime.tick(0)
        rows = {row["id"]: row for row in self.runtime.latest_state["tracked"]}
        self.assertEqual(sorted(rows), ["site:example.org", "site:mail.example.org"])
        self.assertEqual(sorted(rows["site:example.org"]["members"]),
                         ["site:cloud.example.org", "site:example.org", "site:live.example.org"])
        self.runtime.handle_message({"op": "classify", "target_id": "site:example.org", "category": "productive"})
        self.assertEqual(self.runtime.resolve_target_id("site:live.example.org"), "site:example.org")

    def test_hosted_projects_need_matching_identity_under_smart(self):
        self.runtime.handle_message({"op": "classify", "target_id": "site:one.pages.dev", "category": "productive"})
        self.runtime.config["site_identity"].update({"one.pages.dev": {}, "two.pages.dev": {}})
        self.runtime.link_sites(set())
        self.assertEqual(self.runtime.resolve_target_id("site:two.pages.dev"), "site:two.pages.dev")
        self.assertEqual(self.runtime.resolve_target_id("site:one.pages.dev"), "site:one.pages.dev")

    def test_smart_subdomains_require_application_identity_not_brand_name(self):
        parent = "site:example.org"
        self.runtime.handle_message({"op": "classify", "target_id": parent, "category": "productive"})
        self.runtime.config["site_names"].update({"example.org": "Brand", "app.example.org": "Brand"})
        self.runtime.link_sites({"app.example.org"})
        self.assertEqual(self.runtime.resolve_target_id("site:app.example.org"), "site:app.example.org")
        self.runtime.config["site_identity"] = {
            "example.org": {"application_name": "Workspace"},
            "app.example.org": {"application_name": "Workspace"},
            "mail.example.org": {"application_name": "Mail"},
        }
        self.runtime.link_sites({"app.example.org", "mail.example.org"})
        self.assertEqual(self.runtime.resolve_target_id("site:app.example.org"), parent)
        self.assertEqual(self.runtime.resolve_target_id("site:mail.example.org"), "site:mail.example.org")

    def test_smart_subdomains_can_share_a_declared_manifest(self):
        parent = "site:example.org"
        self.runtime.handle_message({"op": "classify", "target_id": parent, "category": "productive"})
        identity = {"manifest": "https://example.org/app.webmanifest"}
        self.runtime.config["site_identity"] = {"example.org": identity, "app.example.org": identity}
        self.runtime.link_sites({"app.example.org"})
        self.assertEqual(self.runtime.resolve_target_id("site:app.example.org"), parent)

    def test_explicit_group_merges_saved_usage_and_preserves_exceptions(self):
        parent, saved = "site:example.org", "site:mail.example.org"
        for target, category in ((parent, "productive"), (saved, "consumption")):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": category})
        now = dt.datetime.now().astimezone()
        bucket, day = agent.current_hour_bucket(now), now.date().isoformat()
        self.runtime.store.add_times({parent: "productive", saved: "consumption", "site:old.example.org": "unclassified"}, 30, bucket, day)
        before = self.runtime.store.history()
        self.runtime.config["independent_targets"] = ["site:detached.example.org"]
        self.runtime.config["ignored_targets"] = ["site:excluded.example.org"]
        self.runtime.config["dismissed_suggestions"] = ["site:dismissed.example.org|site:example.org"]
        self.assertTrue(self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "example.org", "mode": "group"})["ok"])
        self.runtime.link_sites({"new.example.org", "detached.example.org", "excluded.example.org", "dismissed.example.org"})
        for domain in ("new", "mail", "old"):
            self.assertEqual(self.runtime.resolve_target_id("site:" + domain + ".example.org"), parent)
        for domain in ("detached", "excluded", "dismissed"):
            site = "site:" + domain + ".example.org"
            self.assertEqual(self.runtime.resolve_target_id(site), site)
        self.assertEqual(self.runtime.store.used_this_hour(parent, bucket), 30)
        self.assertEqual(self.runtime.store.target_today(day), {parent: 90})
        self.assertEqual(self.runtime.store.history(), before)
        self.assertNotIn(saved, self.runtime.config["targets"])
        self.runtime.store.close()
        self.runtime = agent.Runtime()
        self.assertEqual(self.runtime.resolve_target_id(saved), parent)
        self.assertEqual(self.runtime.config["targets"][parent]["category"], "productive")
        self.assertEqual(self.runtime.store.used_this_hour(parent, bucket), 30)

    def test_explicit_smart_merges_existing_sites_when_identity_arrives_later(self):
        parent, child, different = "site:example.org", "site:app.example.org", "site:mail.example.org"
        for target in (parent, child, different):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "neutral"})
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "example.org", "mode": "smart"})
        self.assertEqual(self.runtime.resolve_target_id(child), child)
        self.runtime.handle_message({"op": "browser_snapshot", "windows": [
            {"id": i, "domain": domain, "site_identity": {"application_name": name}}
            for i, (domain, name) in enumerate((("example.org", "Workspace"), ("app.example.org", "Workspace"), ("mail.example.org", "Mail")))
        ]})
        self.assertEqual(self.runtime.resolve_target_id(child), parent)
        self.assertEqual(self.runtime.resolve_target_id(different), different)

    def test_default_smart_automatically_merges_matching_saved_entries(self):
        parent, child = "site:example.org", "site:app.example.org"
        for target in (parent, child):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "neutral"})
        self.runtime.config["site_identity"] = {domain: {"application_name": "Workspace"}
                                                for domain in ("example.org", "app.example.org")}
        self.runtime.link_sites({"app.example.org"})
        self.assertEqual(self.runtime.resolve_target_id(child), parent)

    def test_grouping_moves_aliases_and_protects_detached_group_members(self):
        parent, child, member = "site:example.org", "site:app.example.org", "app:workspace"
        for target in (parent, child, member):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "neutral"})
        self.runtime.handle_message({"op": "merge", "source": member, "destination": child})
        self.runtime.config["independent_targets"] = [member]
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "example.org", "mode": "group"})
        self.assertEqual(self.runtime.resolve_target_id(child), child)
        self.runtime.config["independent_targets"] = []
        self.runtime.reconcile_targets()
        self.assertEqual(self.runtime.resolve_target_id(child), parent)
        self.assertEqual(self.runtime.resolve_target_id(member), parent)

    def test_explicit_group_keeps_selected_site_settings_even_when_parent_exists(self):
        parent, child, grandchild = "site:example.org", "site:tools.example.org", "site:app.tools.example.org"
        for target in (parent, child, grandchild):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "neutral"})
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "example.org", "mode": "separate"})
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "tools.example.org", "mode": "group"})
        self.assertEqual(self.runtime.resolve_target_id(child), child)
        self.assertEqual(self.runtime.resolve_target_id(grandchild), child)

    def test_mode_selection_updates_the_domain_family_and_shares_quota(self):
        for target in ("site:example.org", "site:tools.example.org"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "tools.example.org", "mode": "separate"})
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "example.org", "mode": "group"})
        self.runtime.link_sites({"new.example.org", "app.tools.example.org", "notexample.org"})
        self.assertEqual(self.runtime.resolve_target_id("site:new.example.org"), "site:example.org")
        self.assertEqual(self.runtime.resolve_target_id("site:app.tools.example.org"), "site:example.org")
        self.assertEqual(self.runtime.resolve_target_id("site:notexample.org"), "site:notexample.org")
        now = dt.datetime.now().astimezone()
        self.runtime.store.add_times({"site:example.org": "consumption"}, 601,
                                    agent.current_hour_bucket(now), now.date().isoformat())
        self.assertEqual(self.runtime.blocked_domains(), ["app.tools.example.org", "example.org", "new.example.org", "tools.example.org"])
        self.runtime.handle_message({"op": "unlink", "target_id": "site:new.example.org"})
        self.runtime.link_sites({"new.example.org"})
        self.assertEqual(self.runtime.resolve_target_id("site:new.example.org"), "site:new.example.org")

    def test_domain_families_use_icann_suffixes_and_keep_hosted_siblings_together(self):
        self.assertEqual(agent.domain_family("one.pages.dev"), "pages.dev")
        self.assertEqual(agent.domain_family("two.pages.dev"), "pages.dev")
        self.assertEqual(agent.domain_family("preview.company.co.uk"), "company.co.uk")
        self.assertEqual(agent.domain_family("preview.other.co.uk"), "other.co.uk")
        self.assertEqual(agent.domain_family("co.uk"), "")
        self.assertEqual(agent.domain_family("127.0.0.1"), "127.0.0.1")

    def test_smart_groups_sibling_projects_with_matching_identity_but_keeps_other_services(self):
        first, matching, different, unknown = ("site:" + domain for domain in
            ("one.pages.dev", "two.pages.dev", "other.pages.dev", "unknown.pages.dev"))
        for target in (first, matching, different, unknown):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "productive"})
        self.runtime.config["site_identity"] = {
            "one.pages.dev": {"application_name": "Charts"},
            "two.pages.dev": {"application_name": "Charts"},
            "other.pages.dev": {"application_name": "Mail"},
        }
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "one.pages.dev", "mode": "smart"})
        self.assertEqual(self.runtime.resolve_target_id(matching), first)
        self.assertEqual(self.runtime.resolve_target_id(different), different)
        self.assertEqual(self.runtime.resolve_target_id(unknown), unknown)
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "one.pages.dev", "mode": "separate"})
        self.runtime.handle_message({"op": "classify", "target_id": "site:new.pages.dev", "category": "productive"})
        self.runtime.config["site_identity"]["new.pages.dev"] = {"application_name": "Charts"}
        self.runtime.reconcile_targets()
        self.assertEqual(self.runtime.resolve_target_id("site:new.pages.dev"), "site:new.pages.dev")

    def test_smart_distinguishes_search_mail_and_cloud_without_service_name_lists(self):
        targets = {"example.org": "Search", "mail.example.org": "Mail", "cloud.example.org": "Cloud", "inbox.example.org": "Mail"}
        for domain in targets:
            self.runtime.handle_message({"op": "classify", "target_id": "site:" + domain, "category": "productive"})
        self.runtime.config["site_identity"] = {domain: {"application_name": name} for domain, name in targets.items()}
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "mail.example.org", "mode": "smart"})
        self.assertEqual(self.runtime.resolve_target_id("site:inbox.example.org"), "site:mail.example.org")
        self.assertEqual(self.runtime.resolve_target_id("site:example.org"), "site:example.org")
        self.assertEqual(self.runtime.resolve_target_id("site:cloud.example.org"), "site:cloud.example.org")

    def test_existing_project_group_rule_migrates_and_groups_pending_projects_without_a_parent_entry(self):
        first, pending = "site:one.pages.dev", "site:two.pages.dev"
        self.runtime.handle_message({"op": "classify", "target_id": first, "category": "productive"})
        now = dt.datetime.now().astimezone()
        self.runtime.store.add_times({pending: "unclassified"}, 30, agent.current_hour_bucket(now), now.date().isoformat())
        history = self.runtime.store.history()
        self.runtime.config["subdomain_rule_schema"] = 1
        self.runtime.config["subdomain_rules"] = {"one.pages.dev": "group"}
        agent.save_config(self.runtime.config)
        self.runtime.store.close()
        self.runtime = agent.Runtime()
        self.runtime.tick(0)
        self.assertEqual(self.runtime.config["subdomain_rules"], {"pages.dev": "group"})
        self.assertEqual(self.runtime.resolve_target_id(pending), first)
        self.assertNotIn("site:pages.dev", self.runtime.config["targets"])
        self.assertEqual(self.runtime.latest_state["tracked"][0]["grouping_scope"], "pages.dev")
        self.assertEqual(self.runtime.store.history(), history)
        self.assertEqual(self.runtime.store.target_today(now.date().isoformat())[first], 30)

    def test_group_does_not_cross_distinct_registrable_domains_or_change_scope_on_new_pages(self):
        first, other, child = "site:one.co.uk", "site:two.co.uk", "site:app.one.co.uk"
        for target in (first, other):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "productive"})
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "one.co.uk", "mode": "group"})
        self.runtime.link_sites({"app.one.co.uk"})
        self.assertEqual(self.runtime.resolve_target_id(child), first)
        self.assertEqual(self.runtime.resolve_target_id(other), other)

    def test_group_subdomain_rule_applies_to_every_domain_of_a_manual_group(self):
        primary, alias = "site:mail.example", "site:inbox.other.example"
        for target in (primary, alias):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "productive"})
        self.runtime.handle_message({"op": "merge", "source": alias, "destination": primary})
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "mail.example", "mode": "group"})
        self.assertEqual(self.runtime.config["subdomain_rules"]["other.example"], "group")
        self.runtime.link_sites({"new.mail.example", "new.inbox.other.example"})
        self.assertEqual(self.runtime.resolve_target_id("site:new.mail.example"), primary)
        self.assertEqual(self.runtime.resolve_target_id("site:new.inbox.other.example"), primary)

    def test_group_merges_neighbouring_projects_under_the_selected_domain_family(self):
        first, second = "site:project-one.host.example", "site:project-two.host.example"
        for target in (first, second):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "productive"})
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "project-one.host.example", "mode": "group"})
        self.assertEqual(self.runtime.resolve_target_id(second), first)
        self.assertEqual(self.runtime.resolve_target_id(first), first)

    def test_pending_site_can_be_merged_into_a_saved_service(self):
        saved, pending = "site:project-one.host.example", "site:project-two.host.example"
        self.runtime.handle_message({"op": "classify", "target_id": saved, "category": "productive"})
        now = dt.datetime.now().astimezone()
        self.runtime.store.add_times({pending: "unclassified"}, 30, agent.current_hour_bucket(now), now.date().isoformat())
        self.assertFalse(self.runtime.handle_message({"op": "merge", "source": "site:unknown.example", "destination": saved})["ok"])
        self.assertFalse(self.runtime.handle_message({"op": "merge", "source": saved, "destination": pending})["ok"])
        self.assertTrue(self.runtime.handle_message({"op": "merge", "source": pending, "destination": saved})["ok"])
        self.assertEqual(self.runtime.resolve_target_id(pending), saved)
        self.assertEqual(self.runtime.store.target_today(now.date().isoformat()), {saved: 30})
        self.assertEqual(self.runtime.store.history()[-1]["productive"], 0.5)
        self.assertNotIn(pending, self.runtime.store.pending_targets())

    def test_background_metadata_groups_sites_without_tracking_background_tabs(self):
        parent, child = "site:example.org", "site:app.example.org"
        self.runtime.handle_message({"op": "classify", "target_id": parent, "category": "productive"})
        self.clients = []
        response = self.runtime.handle_message({"op": "browser_snapshot", "windows": [], "site_metadata": [
            {"domain": domain, "site_name": "Workspace", "site_identity": {"application_name": "Workspace"}}
            for domain in ("example.org", "app.example.org")
        ]})
        self.runtime.tick(2)
        self.assertEqual(self.runtime.resolve_target_id(child), parent)
        self.assertEqual(self.runtime.browser_windows, {})
        self.assertEqual(response["blocked_tab_ids"], [])
        self.assertEqual(self.runtime.latest_state["diagnostics"]["matched_sites"], 0)
        self.assertEqual(self.runtime.store.target_today(dt.date.today().isoformat()), {})
        self.runtime.handle_message({"op": "browser_snapshot", "windows": [], "site_metadata": "invalid"})
        self.runtime.handle_message({"op": "browser_snapshot", "windows": [], "site_metadata": [None]})

    def test_snapshot_identity_is_local_sanitized_and_does_not_fetch_manifest(self):
        self.runtime.handle_message({"op": "browser_snapshot", "windows": [{"id": 1, "domain": "app.example.org",
            "site_identity": {"application_name": "  Workspace   App ", "manifest": "https://example.org/app.json?token=private#state"}}]})
        self.assertEqual(self.runtime.config["site_identity"]["app.example.org"], {
            "application_name": "Workspace App", "manifest": "https://example.org/app.json"})
        self.runtime.handle_message({"op": "browser_snapshot", "windows": [{"id": 1, "domain": "app.example.org",
            "site_identity": {"application_name": "Workspace", "manifest": "https://other.example.org/manifest.json"}}]})
        self.assertEqual(self.runtime.config["site_identity"]["app.example.org"]["manifest"], "")

    def test_late_metadata_groups_site_and_combines_initial_history(self):
        parent, child = "site:example.org", "site:app.example.org"
        self.runtime.handle_message({"op": "classify", "target_id": parent, "category": "productive"})
        self.runtime.config["site_identity"]["example.org"] = {"application_name": "Workspace"}
        self.clients = [{"app_id": "chromium", "window_title": "Inbox - Chromium", "address": "0x123"}]
        window = {"id": 1, "title": "Inbox", "domain": "app.example.org", "tab_id": 10}
        self.runtime.handle_message({"op": "browser_snapshot", "windows": [window]})
        self.runtime.tick(1)
        self.assertEqual(self.runtime.latest_state["tracked"][0]["id"], child)
        self.runtime.handle_message({"op": "browser_snapshot", "windows": [
            {**window, "site_identity": {"application_name": "Workspace"}}]})
        self.runtime.tick(2)
        self.assertEqual([r["id"] for r in self.runtime.latest_state["tracked"]], [parent])
        now = dt.datetime.now().astimezone()
        usage = self.runtime.store.target_today(now.date().isoformat())
        self.assertNotIn(child, usage)
        self.assertEqual(usage[parent], 3)

    def test_new_web_app_uses_parent_group_rule_without_browser_extension(self):
        parent = "site:example.org"
        self.runtime.handle_message({"op": "classify", "target_id": parent, "category": "productive"})
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "example.org", "mode": "group"})
        self.clients = [{"app_id": "chrome-app.example.org__-default", "window_title": "Workspace", "address": "0x123"}]
        self.runtime.tick(3)
        self.assertEqual([row["id"] for row in self.runtime.latest_state["tracked"]], [parent])
        self.assertEqual(self.runtime.latest_state["tracked"][0]["today_seconds"], 3)

    def test_detached_entries_still_have_manual_suggestions(self):
        rows = [{"id": target, "name": "service.example", "configured": True}
                for target in ("app:chrome-service.example__-default", "site:service.example")]
        self.runtime.config["independent_targets"] = [row["id"] for row in rows]
        self.assertEqual(len(self.runtime.group_suggestions(rows)), 1)
        self.assertEqual(self.runtime.resolve_target_id(rows[0]["id"]), rows[0]["id"])
        self.runtime.config["dismissed_suggestions"] = ["|".join(sorted(row["id"] for row in rows))]
        self.assertEqual(self.runtime.group_suggestions(rows), [])

    def test_review_classification(self):
        self.runtime.tick(agent.REVIEW_MIN_SECONDS)
        state = self.runtime.latest_state
        self.assertEqual(state["focused_id"], "app:test")
        self.assertEqual(state["tracked"][0]["category"], "unclassified")
        self.clients = []
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["tracked"][0]["visible_windows"], 0)
        self.assertTrue(self.runtime.latest_state["tracked"][0]["review"])
        self.assertTrue(self.runtime.handle_message({
            "op": "classify", "target_id": "app:test", "category": "productive"
        })["ok"])
        self.assertEqual(self.runtime.store.pending_targets(), {})
        self.assertEqual(self.runtime.config["targets"]["app:test"]["category"], "productive")

    def test_site_metadata_names_are_dynamic_and_persisted(self):
        self.clients = [{"app_id": "chromium", "window_title": "Workspace - Chromium", "address": "0x123"}]
        self.runtime.handle_message({"op": "browser_snapshot", "windows": [
            {"id": 1, "title": "Workspace", "domain": "tools.example.org", "site_name": "New Service"}
        ]})
        self.runtime.tick(agent.REVIEW_MIN_SECONDS)
        row = self.runtime.latest_state["tracked"][0]
        self.assertEqual(row["id"], "site:tools.example.org")
        self.assertEqual(row["name"], "New Service")
        self.assertEqual(agent.load_config()["site_names"]["tools.example.org"], "New Service")
        self.clients = []
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["tracked"][0]["name"], "New Service")

    def test_exclude_and_track_again(self):
        self.runtime.tick(2)
        self.assertTrue(self.runtime.store.pending_targets())
        self.assertTrue(self.runtime.handle_message({"op": "exclude", "target_id": "app:test"})["ok"])
        self.runtime.tick(1)
        self.assertEqual(self.runtime.latest_state["tracked"], [])
        self.assertEqual(self.runtime.store.pending_targets(), {})
        self.assertEqual(self.runtime.latest_state["ignored_targets"], ["app:test"])
        self.assertTrue(self.runtime.handle_message({"op": "unexclude", "target_id": "app:test"})["ok"])
        self.runtime.tick(1)
        self.assertEqual(self.runtime.latest_state["tracked"][0]["category"], "unclassified")

    def test_track_again_restores_review_without_reopening_and_survives_restart(self):
        target = "app:test"
        self.runtime.tick(2)
        self.runtime.handle_message({"op": "exclude", "target_id": target})
        self.clients = []
        self.runtime.handle_message({"op": "unexclude", "target_id": target})
        self.runtime.store.close()
        self.runtime = agent.Runtime()
        self.runtime.tick(0)
        row = self.runtime.latest_state["tracked"][0]
        self.assertEqual(row["id"], target)
        self.assertFalse(row["configured"])
        self.assertEqual(row["today_seconds"], 0)
        self.runtime.handle_message({"op": "exclude", "target_id": target})
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["tracked"], [])
        self.runtime.handle_message({"op": "unexclude", "target_id": target})
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "productive"})
        self.assertEqual(self.runtime.config["review_targets"], [])

    def test_track_again_joins_existing_domain_group_without_reopening(self):
        root, child = "site:one.pages.dev", "site:two.pages.dev"
        self.clients = []
        self.runtime.handle_message({"op": "classify", "target_id": root, "category": "productive"})
        self.runtime.handle_message({"op": "set_subdomain_rule", "domain": "one.pages.dev", "mode": "group"})
        self.runtime.handle_message({"op": "exclude", "target_id": child})
        self.runtime.handle_message({"op": "unexclude", "target_id": child})
        self.runtime.tick(0)
        self.assertEqual(self.runtime.resolve_target_id(child), root)
        self.assertEqual(self.runtime.config["review_targets"], [])
        self.assertIn(child, self.runtime.latest_state["tracked"][0]["members"])
        self.assertEqual(self.runtime.latest_state["tracked"][0]["today_seconds"], 0)

    def test_restored_review_entry_can_merge_manually_or_with_smart_metadata(self):
        root, child = "site:one.pages.dev", "site:two.pages.dev"
        self.clients = []
        self.runtime.handle_message({"op": "classify", "target_id": root, "category": "productive"})
        self.runtime.handle_message({"op": "exclude", "target_id": child})
        self.runtime.handle_message({"op": "unexclude", "target_id": child})
        self.assertEqual(self.runtime.resolve_target_id(child), child)
        self.runtime.config["site_identity"] = {"one.pages.dev": {"application_name": "Charts"}, "two.pages.dev": {"application_name": "Charts"}}
        self.runtime.reconcile_targets()
        self.assertEqual(self.runtime.resolve_target_id(child), root)
        self.assertEqual(self.runtime.config["review_targets"], [])
        other = "app:restored"
        self.runtime.handle_message({"op": "exclude", "target_id": other})
        self.runtime.handle_message({"op": "unexclude", "target_id": other})
        self.assertTrue(self.runtime.handle_message({"op": "merge", "source": other, "destination": root})["ok"])
        self.assertEqual(self.runtime.resolve_target_id(other), root)
        self.assertEqual(self.runtime.config["review_targets"], [])

    def test_track_again_rejects_invalid_target_ids(self):
        for target in ("", "site:", "app:", "unknown"):
            self.assertFalse(self.runtime.handle_message({"op": "unexclude", "target_id": target})["ok"])
        self.assertEqual(self.runtime.config["review_targets"], [])

    def test_exclude_classified_group_preserves_history_settings_and_stops_limits(self):
        for target in ("app:test", "site:example.org"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": "site:example.org", "quota_minutes": 1})
        self.runtime.handle_message({"op": "merge", "source": "app:test", "destination": "site:example.org"})
        self.runtime.tick(61)
        self.assertEqual(self.runtime.blocked_domains(), ["example.org"])
        self.closed.clear()
        history = self.runtime.store.history()
        settings = dict(self.runtime.config["targets"]["site:example.org"])
        self.assertTrue(self.runtime.handle_message({"op": "exclude", "target_id": "app:test"})["ok"])
        self.runtime.tick(5)
        self.assertEqual(self.closed, [])
        self.assertEqual(self.runtime.blocked_domains(), [])
        self.assertEqual(self.runtime.latest_state["tracked"], [])
        self.assertEqual(self.runtime.store.history(), history)
        self.runtime.store.close()
        self.runtime = agent.Runtime()
        self.assertEqual(self.runtime.config["targets"]["site:example.org"], settings)
        self.assertEqual(self.runtime.config["ignored_targets"], ["site:example.org"])
        self.runtime.handle_message({"op": "unexclude", "target_id": "app:test"})
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["tracked"][0]["category"], "consumption")
        self.assertEqual(self.runtime.latest_state["tracked"][0]["quota_seconds"], 60)
        self.assertEqual(self.runtime.blocked_domains(), ["example.org"])

    def test_browser_connection_waits_for_launch_and_resets_after_close(self):
        with mock.patch.object(agent, "browser_is_running", return_value=False):
            self.runtime.tick(0)
            self.assertFalse(self.runtime.latest_state["diagnostics"]["browser_connection_expected"])
        with mock.patch.object(agent, "browser_is_running", return_value=True), mock.patch.object(agent.time, "monotonic", return_value=100):
            self.runtime.tick(0)
            self.assertFalse(self.runtime.latest_state["diagnostics"]["browser_connection_expected"])
        self.runtime.paused = True
        with mock.patch.object(agent, "browser_is_running", return_value=True), mock.patch.object(agent.time, "monotonic", return_value=109):
            self.runtime.tick(0)
            self.assertTrue(self.runtime.latest_state["diagnostics"]["browser_connection_expected"])
        with mock.patch.object(agent, "browser_is_running", return_value=False):
            self.runtime.tick(0)
            self.assertFalse(self.runtime.latest_state["diagnostics"]["browser_running"])
            self.assertFalse(self.runtime.latest_state["diagnostics"]["browser_connection_expected"])
            self.assertIsNone(self.runtime.browser_opened_at)

    def test_browser_detection_includes_other_workspaces(self):
        with mock.patch.object(agent, "hypr_json", return_value=[{"class": "Chromium", "mapped": True, "workspace": {"id": 7}}]):
            self.assertTrue(agent.browser_is_running())
        for client in ({"class": "foot"}, {"class": "chromium", "mapped": False}):
            with mock.patch.object(agent, "hypr_json", return_value=[client]):
                self.assertFalse(agent.browser_is_running())

    def test_focused_browser_uses_matching_site(self):
        self.clients = [{"app_id": "chromium", "window_title": "A post - Chromium", "address": "0x123"}]
        self.runtime.browser_windows = {"1": {"title": "A post", "domain": "x.com"}}
        self.runtime.last_browser_snapshot = time.monotonic()
        self.runtime.tick(1)
        self.assertEqual(self.runtime.latest_state["focused_id"], "site:x.com")
        self.assertEqual([row["id"] for row in self.runtime.latest_state["tracked"]], ["site:x.com"])

    def test_web_app_and_browser_site_share_one_limit_and_close_correct_window(self):
        app_id = "app:chrome-x.com__-default"
        site_id = "site:x.com"
        self.runtime.config["targets"][app_id] = {
            "name": "chrome-x.com__-default", "category": "consumption", "quota_minutes": 1,
            "limit_action": "close",
        }
        self.runtime.config["targets"][site_id] = {
            "name": "x.com", "category": "consumption", "quota_minutes": 1,
            "limit_action": "close",
        }
        now = dt.datetime.now().astimezone()
        bucket = agent.current_hour_bucket(now)
        day = now.date().isoformat()
        self.runtime.store.add_times({app_id: "consumption"}, 20, bucket, day)
        self.runtime.store.add_times({site_id: "consumption"}, 20, bucket, day)
        self.clients = [
            {"app_id": "chrome-x.com__-default", "window_title": "X", "address": "0x123"},
            {"app_id": "chromium", "window_title": "X post - Chromium", "address": "0x456"},
        ]
        self.runtime.browser_windows = {"1": {"title": "X post", "domain": "x.com"}}
        self.runtime.last_browser_snapshot = time.monotonic()
        self.runtime.tick(20)
        rows = self.runtime.latest_state["tracked"]
        self.assertEqual([row["id"] for row in rows], [site_id])
        self.assertEqual(rows[0]["visible_windows"], 2)
        self.assertEqual(rows[0]["used_seconds"], 60)
        self.assertEqual(rows[0]["remaining_seconds"], 0)
        self.assertEqual([client["address"] for client in self.closed], ["0x123"])
        self.assertEqual(self.runtime.blocked_domains(), ["x.com"])
        self.assertNotIn(app_id, self.runtime.config["targets"])
        self.assertEqual(self.runtime.config["service_links"][app_id], site_id)
        self.assertTrue(rows[0]["linked"])
        self.assertEqual(self.runtime.store.used_this_hour(app_id, bucket), 0)
        self.assertTrue(self.runtime.handle_message({
            "op": "set_quota", "target_id": app_id, "quota_minutes": 5,
        })["ok"])
        self.assertEqual(self.runtime.config["targets"][site_id]["quota_minutes"], 5)

    def test_web_app_only_settings_become_site_settings(self):
        app_id = "app:chrome-youtube.com__-default"
        self.runtime.config["targets"][app_id] = {
            "name": "chrome-youtube.com__-default", "category": "consumption", "quota_minutes": 7,
        }
        self.runtime.reconcile_targets()
        self.assertNotIn(app_id, self.runtime.config["targets"])
        self.assertEqual(self.runtime.config["targets"]["site:youtube.com"], {
            "name": "youtube.com", "category": "consumption", "quota_minutes": 7,
        })
        self.assertEqual(self.runtime.config["service_links"][app_id], "site:youtube.com")

    def test_site_settings_win_when_linking_an_existing_web_app(self):
        app_id = "app:chrome-beeper.com__-default"
        site_id = "site:beeper.com"
        self.runtime.config["targets"][app_id] = {"name": "Beeper", "category": "consumption", "quota_minutes": 5}
        self.runtime.config["targets"][site_id] = {"name": "beeper.com", "category": "neutral", "quota_minutes": 12}
        with mock.patch.object(agent, "app_display_name", return_value="Beeper"):
            self.runtime.reconcile_targets()
        self.assertNotIn(app_id, self.runtime.config["targets"])
        self.assertEqual(self.runtime.config["targets"][site_id]["category"], "neutral")
        self.assertEqual(self.runtime.config["targets"][site_id]["quota_minutes"], 12)

    def test_native_app_names_do_not_create_links(self):
        with mock.patch.object(agent, "desktop_app_domains", return_value={}):
            self.assertEqual(agent.service_site_for_app("beeper"), "")
            self.assertEqual(agent.service_site_for_app("chromium"), "")

    def test_desktop_launcher_url_links_app_without_name_match(self):
        applications = pathlib.Path(self.temp.name) / "data" / "applications"
        applications.mkdir(parents=True)
        (applications / "calendar.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=My Calendar\n"
            "StartupWMClass=CalendarApp\nExec=chromium --app=https://calendar.example.com/home\n"
        )
        agent.desktop_app_domains.cache_clear()
        self.addCleanup(agent.desktop_app_domains.cache_clear)
        with mock.patch.dict("os.environ", {"XDG_DATA_HOME": str(applications.parent), "XDG_DATA_DIRS": ""}):
            self.assertEqual(agent.service_site_for_app("calendarapp"), "site:calendar.example.com")

    def test_all_visible_apps_accrue_time_without_focus(self):
        self.clients = [
            {"app_id": "First", "window_title": "First", "address": "0x123"},
            {"app_id": "Second", "window_title": "Second", "address": "0x456"},
        ]
        self.runtime.tick(10)
        rows = {row["id"]: row for row in self.runtime.latest_state["tracked"]}
        self.assertEqual(set(rows), {"app:first", "app:second"})
        self.assertTrue(rows["app:first"]["focused"])
        self.assertFalse(rows["app:second"]["focused"])
        self.assertEqual(rows["app:second"]["visible_windows"], 1)
        self.assertGreaterEqual(rows["app:second"]["today_seconds"], 10)

    def test_consumption_limit_and_pause(self):
        self.runtime.handle_message({"op": "classify", "target_id": "app:test", "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": "app:test", "quota_minutes": 1})
        self.runtime.tick(61)
        self.assertEqual(self.runtime.latest_state["tracked"][0]["remaining_seconds"], 0)
        self.assertEqual(len(self.closed), 1)
        self.runtime.handle_message({"op": "pause", "paused": True})
        self.runtime.tick(1)
        self.assertFalse(self.runtime.latest_state["working"])
        self.assertEqual(len(self.closed), 1)

    def test_screen_time_counts_overlapping_apps_once_and_survives_restart(self):
        self.clients.append({"app_id": "Second", "window_title": "Second", "address": "0x456"})
        self.runtime.tick(10)
        self.assertEqual(self.runtime.latest_state["today"]["screen_seconds"], 10)
        self.assertEqual(sum(row["today_seconds"] for row in self.runtime.latest_state["tracked"]), 20)
        started = self.runtime.latest_state["today"]["screen_started_at"]
        self.runtime.store.close()
        self.runtime = agent.Runtime()
        self.runtime.tick(5)
        self.assertEqual(self.runtime.latest_state["today"]["screen_seconds"], 15)
        self.assertEqual(self.runtime.latest_state["today"]["screen_started_at"], started)

    def test_screen_time_stops_when_tracking_is_inactive(self):
        self.runtime.tick(3)
        for locked, idle in [(True, False), (False, True)]:
            with mock.patch.object(agent, "session_status", return_value=(locked, idle)):
                self.runtime.tick(10)
        with mock.patch.object(agent, "in_work_hours", return_value=False):
            self.runtime.tick(10)
        self.runtime.paused = True
        self.runtime.tick(10)
        self.runtime.paused = False
        self.runtime.config["ignored_targets"] = ["app:test"]
        self.runtime.tick(10)
        self.clients = []
        self.runtime.tick(10)
        self.assertEqual(self.runtime.latest_state["today"]["screen_seconds"], 3)

    def test_screen_time_keeps_legacy_history_unknown_and_new_days_separate(self):
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        with self.runtime.store.db:
            self.runtime.store.db.execute(
                "INSERT INTO daily_usage VALUES(?, 'app:test', 'neutral', 60)", (yesterday,))
        self.runtime.tick(7)
        history = {row["day"]: row for row in self.runtime.store.history()}
        self.assertNotIn("screen_seconds", history[yesterday])
        self.assertEqual(history[dt.date.today().isoformat()]["screen_seconds"], 7)
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        self.runtime.store.add_times({}, 10, tomorrow, tomorrow)
        self.assertEqual(self.runtime.store.history()[-1]["screen_seconds"], 0)

    def test_limit_action_is_per_target_and_defaults_to_close(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 1})
        self.assertFalse(self.runtime.handle_message({
            "op": "set_limit_action", "target_id": target, "action": "unknown"
        })["ok"])
        self.assertTrue(self.runtime.handle_message({
            "op": "set_limit_action", "target_id": target, "action": "keep_open"
        })["ok"])
        self.runtime.tick(61)
        self.assertEqual(self.closed, [])
        self.assertEqual(self.runtime.latest_state["tracked"][0]["limit_action"], "keep_open")
        self.assertTrue(self.runtime.handle_message({
            "op": "set_limit_action", "target_id": target, "action": "close"
        })["ok"])
        self.runtime.tick(0)
        self.assertEqual(len(self.closed), 1)

    def test_notify_action_sends_one_alert_per_hour(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 1})
        self.runtime.handle_message({"op": "set_limit_action", "target_id": target, "action": "notify"})
        with mock.patch.object(agent.subprocess, "Popen") as notify:
            self.runtime.tick(61)
            self.runtime.tick(1)
        self.assertEqual(self.closed, [])
        notify.assert_called_once()
        args = notify.call_args.args[0]
        self.assertIn("Time limit reached · Test", args)
        self.assertIn("Test stays open.", args)
        self.assertEqual(args[-2:], ["-A", "snooze=5 more minutes"])

    def test_reclassification_keeps_quota_edit(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "productive"})
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 17})
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "neutral"})
        self.assertEqual(self.runtime.config["targets"][target]["category"], "neutral")
        self.assertEqual(self.runtime.config["targets"][target]["quota_minutes"], 17)

    def test_today_does_not_reuse_yesterdays_totals(self):
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        with self.runtime.store.db:
            self.runtime.store.db.execute(
                "INSERT INTO daily_usage VALUES(?,?,?,?)", (yesterday, "app:test", "productive", 600)
            )
        self.clients = []
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["today"]["day"], dt.date.today().isoformat())
        self.assertEqual(self.runtime.latest_state["today"].get("productive", 0), 0)

    def test_schedule_edits_and_overnight_hours(self):
        schedule = {"weekdays": [0], "start": "22:00", "end": "02:00"}
        self.assertTrue(self.runtime.handle_message({"op": "set_schedule", "schedule": schedule})["ok"])
        self.assertEqual(self.runtime.config["schedule"], schedule)
        monday = dt.datetime(2026, 9, 28, 23, 0)
        self.assertTrue(ORIGINAL_IN_WORK_HOURS(monday, schedule))
        self.assertTrue(ORIGINAL_IN_WORK_HOURS(monday + dt.timedelta(hours=2), schedule))
        self.assertFalse(ORIGINAL_IN_WORK_HOURS(monday + dt.timedelta(hours=4), schedule))
        self.assertFalse(self.runtime.handle_message({
            "op": "set_schedule", "schedule": {"weekdays": [7], "start": "08:00", "end": "17:00"}
        })["ok"])

    def test_all_day_schedule_respects_selected_days(self):
        schedule = {"weekdays": [0], "start": "00:00", "end": "00:00"}
        self.assertTrue(self.runtime.handle_message({"op": "set_schedule", "schedule": schedule})["ok"])
        self.assertEqual(agent.load_config()["schedule"], schedule)
        self.assertTrue(ORIGINAL_IN_WORK_HOURS(dt.datetime(2026, 9, 28, 0, 0), schedule))
        self.assertTrue(ORIGINAL_IN_WORK_HOURS(dt.datetime(2026, 9, 28, 23, 59), schedule))
        self.assertFalse(ORIGINAL_IN_WORK_HOURS(dt.datetime(2026, 9, 29, 0, 0), schedule))

    def test_system_portal_can_be_reviewed(self):
        portal = {"class": "xdg-desktop-portal-gtk", "address": "0x999",
                  "workspace": {"id": 1}, "size": [400, 300]}
        with mock.patch.object(agent, "hypr_json", side_effect=lambda command:
                               [{"activeWorkspace": {"id": 1}}] if command == "monitors" else [portal]):
            self.assertEqual(ORIGINAL_VISIBLE_CLIENTS(), [{
                "app_id": "xdg-desktop-portal-gtk", "window_title": "", "address": "0x999"
            }])
        day = dt.date.today().isoformat()
        self.runtime.store.add_times({"app:xdg-desktop-portal-gtk": "unclassified"}, agent.REVIEW_MIN_SECONDS, "bucket", day)
        self.runtime.tick(0)
        self.assertEqual(list(self.runtime.store.pending_targets()), ["app:xdg-desktop-portal-gtk"])
        self.assertTrue(any(row["id"] == "app:xdg-desktop-portal-gtk"
                            for row in self.runtime.latest_state["tracked"]))


if __name__ == "__main__":
    unittest.main()
