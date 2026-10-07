"""launcher.py: what ster needs from the agent app, without importing its web server."""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agent_app import launcher
from helpers import FakeModel, free_range


class FakePage:
    """Something answering /api/status the way the agent page does, for a given project."""

    def __init__(self, root, port=0, ster_port=8765):
        outer = self
        self.root, self.ster_port = root, ster_port

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: V105
                pass

            def do_GET(self):  # noqa: V105
                body = json.dumps(
                    {
                        "root": outer.root,
                        "ster": True,
                        "ster_port": outer.ster_port,
                    }
                ).encode()
                self.send_response(200 if self.path == "/api/status" else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Silent(BaseHTTPRequestHandler):
    """Another service on the port: answers, but not as the agent page does."""

    def log_message(self, *a):  # noqa: V105
        pass

    def do_GET(self):  # noqa: V105
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"hi")


class UsableAgent(unittest.TestCase):  # noqa: V102
    def setUp(self):
        self.recipes = Path(tempfile.mkdtemp())  # no recipes: only what the environment names
        self.models = []

    def tearDown(self):
        for m in self.models:
            m.close()

    def usable(self, env):
        return launcher.has_usable_agent(env, recipes_dir=self.recipes)

    def test_nothing_set_up_is_not_usable(self):
        self.assertFalse(self.usable({}))

    def test_a_command_whose_program_exists_is_usable(self):
        self.assertTrue(self.usable({"ASK_AGENT_CMD": f"{sys.executable} -c pass"}))

    def test_a_command_whose_program_is_missing_is_not(self):
        self.assertFalse(self.usable({"ASK_AGENT_CMD": "no-such-program-xyz --ask"}))

    def test_a_model_server_with_a_model_that_can_call_tools_is_usable(self):
        m = FakeModel(models=["big"], tools_capable=("big",))
        self.models.append(m)
        self.assertTrue(self.usable({"ASK_MODEL_URL": m.endpoint}))

    def test_a_model_server_with_no_such_model_is_not(self):
        m = FakeModel(models=["plain"], tools_capable=())
        self.models.append(m)
        self.assertFalse(self.usable({"ASK_MODEL_URL": m.endpoint}))

    def test_a_model_server_that_is_down_is_not(self):
        self.assertFalse(self.usable({"ASK_MODEL_URL": "http://127.0.0.1:9/v1"}))

    def test_a_recipe_whose_program_exists_is_usable(self):
        (self.recipes / "r.json").write_text(
            json.dumps({"label": "R", "binary": sys.executable, "command": ["x"]})
        )
        self.assertTrue(self.usable({}))

    def test_a_recipe_whose_program_is_missing_is_not(self):
        (self.recipes / "r.json").write_text(
            json.dumps({"label": "R", "binary": "no-such-program-xyz", "command": ["x"]})
        )
        self.assertFalse(self.usable({}))

    def test_the_shipped_recipes_are_the_default(self):
        # no recipes folder given: the package's own, so the answer is about this machine; it must at least not fail
        self.assertIn(launcher.has_usable_agent({}), (True, False))

    def test_asking_does_not_import_the_web_server(self):
        code = "import sys; from agent_app import launcher; launcher.has_usable_agent({}); print('agent_app.server' in sys.modules or 'fastapi' in sys.modules)"
        import subprocess

        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
            timeout=30,
        )
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


class FindingAPage(unittest.TestCase):  # noqa: V102
    def setUp(self):
        self.project = str(Path(tempfile.mkdtemp()).resolve())
        self.things = []
        self.start = free_range()
        self.ports = range(self.start, self.start + 4)

    def tearDown(self):
        for t in self.things:
            t.close() if hasattr(t, "close") else t.shutdown()

    def page(self, root, port, **kw):
        p = FakePage(root, port, **kw)
        self.things.append(p)
        return p

    def test_the_page_for_this_project_is_found(self):
        self.page(self.project, self.start + 1)
        self.assertEqual(
            launcher.find_page(Path(self.project), ports=self.ports),
            f"http://127.0.0.1:{self.start + 1}",
        )

    def test_a_page_tied_to_another_ster_is_not_the_one_asked_for(self):
        self.page(self.project, self.start, ster_port=8766)
        self.assertIsNone(launcher.find_page(Path(self.project), ports=self.ports, ster_port=8765))
        self.assertIsNotNone(
            launcher.find_page(Path(self.project), ports=self.ports, ster_port=8766)
        )

    def test_the_page_is_found_by_folder_and_ster_port_only(self):
        self.page(self.project, self.start, ster_port=8766)
        self.assertIsNone(launcher.find_page(Path(self.project), ports=self.ports, ster_port=8765))
        self.assertIsNotNone(
            launcher.find_page(Path(self.project), ports=self.ports, ster_port=8766)
        )

    def test_the_command_carries_no_file_or_context(self):
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            launcher.ensure_running(
                Path(self.project), "127.0.0.1", 8765, ports=self.ports, wait=0.2
            )
        cmd = popen.call_args.args[0]
        self.assertFalse([a for a in cmd if a in ("--ster-file", "--ster-context")])

    def test_a_page_for_another_project_is_not_this_ones(self):
        self.page("/some/other/project", self.start)
        self.assertIsNone(launcher.find_page(Path(self.project), ports=self.ports))

    def test_nothing_running_finds_nothing(self):
        self.assertIsNone(launcher.find_page(Path(self.project), ports=self.ports))

    def test_another_service_on_a_port_is_ignored_and_the_search_goes_on(self):
        other = ThreadingHTTPServer(("127.0.0.1", self.start), Silent)
        threading.Thread(target=other.serve_forever, daemon=True).start()
        self.things.append(other)
        self.page(self.project, self.start + 2)
        self.assertEqual(
            launcher.find_page(Path(self.project), ports=self.ports),
            f"http://127.0.0.1:{self.start + 2}",
        )

    def test_two_projects_each_find_their_own_page(self):
        other = str(Path(tempfile.mkdtemp()).resolve())
        self.page(self.project, self.start)
        self.page(other, self.start + 1)
        self.assertEqual(
            launcher.find_page(Path(other), ports=self.ports), f"http://127.0.0.1:{self.start + 1}"
        )

    def test_the_project_is_compared_by_its_real_path(self):
        link = Path(tempfile.mkdtemp()) / "link"
        link.symlink_to(self.project)
        self.page(self.project, self.start)
        self.assertIsNotNone(launcher.find_page(link, ports=self.ports))


class StartCommand(unittest.TestCase):  # noqa: V102
    """The command-line entry that the launcher starts."""

    def test_options_become_the_settings_the_server_reads(self):
        from agent_app import cli

        env: dict[str, str] = {}
        cli.apply(
            cli.parse(
                ["--project", "/p", "--port", "9001", "--ster-host", "h", "--ster-port", "9002"]
            ),
            env,
        )
        self.assertEqual(
            env,
            {
                "ASK_PROJECT": "/p",
                "ASK_PORT": "9001",
                "ASK_STER_HOST": "h",
                "ASK_STER_PORT": "9002",
            },
        )

    def test_options_not_given_leave_the_environment_alone(self):
        from agent_app import cli

        env = {"ASK_PORT": "1234"}
        cli.apply(cli.parse([]), env)
        self.assertEqual(env, {"ASK_PORT": "1234"})

    def test_a_folder_that_is_not_a_ster_project_does_not_crash_the_start(self):
        from agent_app import cli, server

        with mock.patch.object(
            server, "ensure_ster", side_effect=FileNotFoundError("no project.json")
        ):
            cli._warm_ster(server)  # prints, does not raise


class Starting(unittest.TestCase):  # noqa: V102
    def setUp(self):
        self.project = Path(tempfile.mkdtemp()).resolve()
        self.start = free_range()
        self.ports = range(self.start, self.start + 4)
        self.pids = []
        self.things = []

    def tearDown(self):
        for pid in self.pids:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        for t in self.things:
            t.close() if hasattr(t, "close") else t.shutdown()

    def test_a_running_page_is_reused_not_started_again(self):
        page = FakePage(str(self.project), self.start + 1)
        self.things.append(page)
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            result = launcher.ensure_running(self.project, "127.0.0.1", 8765, ports=self.ports)
        popen.assert_not_called()
        self.assertEqual(
            (result.url, result.started, result.error),
            (f"http://127.0.0.1:{self.start + 1}", False, None),
        )

    def test_a_page_on_another_ster_does_not_stand_in_a_new_one_is_started(self):
        self.things.append(FakePage(str(self.project), self.start, ster_port=8766))
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            launcher.ensure_running(self.project, "127.0.0.1", 8765, ports=self.ports, wait=0.2)
        popen.assert_called_once()
        cmd = popen.call_args.args[0]
        port = int(cmd[cmd.index("--port") + 1])
        self.assertIn(port, self.ports)  # a free port of the range...
        self.assertNotEqual(port, self.start)  # ...and not the one the other ster's page holds

    def test_it_really_starts_the_page_for_the_project(self):
        result = launcher.ensure_running(self.project, "127.0.0.1", 8765, ports=self.ports, wait=40)
        self.pids.append(result.pid)
        self.assertEqual((result.error, result.started), (None, True))
        self.assertEqual(result.url, f"http://127.0.0.1:{self.start}")  # the first free port
        self.assertEqual(launcher.find_page(self.project, ports=self.ports), result.url)
        self.assertTrue(
            (self.project / ".ster" / "agent-app" / "page.log").exists()
        )  # its output goes in the project

    def test_asking_again_gives_the_same_page(self):
        first = launcher.ensure_running(self.project, "127.0.0.1", 8765, ports=self.ports, wait=40)
        self.pids.append(first.pid)
        second = launcher.ensure_running(self.project, "127.0.0.1", 8765, ports=self.ports)
        self.assertEqual((second.url, second.started), (first.url, False))

    def test_the_command_names_the_project_the_port_and_where_ster_is(self):
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            launcher.ensure_running(self.project, "10.0.0.5", 9000, ports=self.ports, wait=0.2)
        cmd, kw = popen.call_args.args[0], popen.call_args.kwargs
        self.assertEqual(cmd[:3], [sys.executable, "-m", "agent_app"])
        pairs = dict(zip(cmd[3::2], cmd[4::2], strict=False))
        self.assertEqual(
            pairs,
            {
                "--project": str(self.project),
                "--port": str(self.start),
                "--ster-host": "10.0.0.5",
                "--ster-port": "9000",
            },
        )
        self.assertEqual(kw["cwd"], self.project)
        self.assertTrue(kw["start_new_session"])  # it outlives ster's terminal

    def test_a_port_taken_by_something_else_is_skipped(self):
        other = ThreadingHTTPServer(("127.0.0.1", self.start), Silent)
        threading.Thread(target=other.serve_forever, daemon=True).start()
        self.things.append(other)
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            launcher.ensure_running(self.project, "127.0.0.1", 8765, ports=self.ports, wait=0.2)
        self.assertIn(str(self.start + 1), popen.call_args.args[0])

    def test_a_page_that_never_answers_is_reported_with_where_to_look(self):
        with mock.patch.object(launcher.subprocess, "Popen"):
            result = launcher.ensure_running(
                self.project, "127.0.0.1", 8765, ports=self.ports, wait=0.3
            )
        self.assertEqual((result.url, result.started), (None, False))
        self.assertIn("page.log", result.error)

    def test_no_free_port_is_reported(self):
        held = []
        for p in self.ports:
            s = socket.socket()
            s.bind(("127.0.0.1", p))
            s.listen()
            held.append(s)
        self.addCleanup(lambda: [s.close() for s in held])
        result = launcher.ensure_running(
            self.project, "127.0.0.1", 8765, ports=self.ports, wait=0.2
        )
        self.assertEqual((result.url, result.started), (None, False))
        self.assertIn(str(self.start), result.error)


if __name__ == "__main__":
    unittest.main()
