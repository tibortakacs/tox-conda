import os
import subprocess
import sys
from contextlib import closing, contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, Dict, Iterator, Optional, Sequence

import pytest
from pytest import MonkeyPatch
from pytest_mock import MockerFixture
from tox.execute.api import ExecuteInstance, ExecuteOptions, ExecuteStatus
from tox.execute.request import ExecuteRequest
from tox.execute.stream import SyncWrite
from tox.pytest import CaptureFixture, ToxProject, ToxProjectCreator
from tox.run import run as tox_run

from tox_conda.plugin import CondaEnvRunner


class TestToxProjectOutcome:
    def __init__(self, code):
        self.code = code

    def assert_success(self):
        assert self.code == 0

class TestToxProject:
    def __init__(self, project_path: Path, ini: dict, monkeypatch: MonkeyPatch):
        self.path = project_path
        for name, content in ini.items():
            Path(self.path / name).write_text(content)
        self.monkeypatch = monkeypatch

    @contextmanager
    def chdir(self, to: Path) -> Iterator[None]:
        cur_dir = os.getcwd()
        os.chdir(str(to or self.path))
        try:
            yield
        finally:
            os.chdir(cur_dir)

    def run(self, *args):
        with self.chdir(self.path):
            # subprocess.run([sys.executable, "-m", "tox"] + list(args))
            # tox_run(list(args))
            with self.monkeypatch.context() as m:
                # m.setattr(tox_env_api, "_CWD", self.path)
                # m.setattr(tox.run, "setup_state", our_setup_state)
                m.setattr(sys, "argv", [sys.executable, "-m", "tox"] + list(args))
                m.setenv("VIRTUALENV_SYMLINK_APP_DATA", "1")
                m.setenv("VIRTUALENV_SYMLINKS", "1")
                m.setenv("VIRTUALENV_PIP", "embed")
                m.setenv("VIRTUALENV_WHEEL", "embed")
                m.setenv("VIRTUALENV_SETUPTOOLS", "embed")
                try:
                    tox_run(args)
                except SystemExit as exception:
                    code = exception.code
        return TestToxProjectOutcome(int(code))

@pytest.fixture(name="tox_project")
def init_fixture(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
):
    def _init(ini: str) -> TestToxProject:
        return TestToxProject(tmp_path, ini, monkeypatch)

    return _init


@pytest.fixture
def mock_conda_env_runner(request, monkeypatch):
    class MockExecuteStatus(ExecuteStatus):
        def __init__(
            self, options: ExecuteOptions, out: SyncWrite, err: SyncWrite, exit_code: int
        ) -> None:
            super().__init__(options, out, err)
            self._exit_code = exit_code

        @property
        def exit_code(self) -> Optional[int]:
            return self._exit_code

        def wait(self, timeout: Optional[float] = None) -> Optional[int]:  # noqa: U100
            return self._exit_code

        def write_stdin(self, content: str) -> None:  # noqa: U100
            return None  # pragma: no cover

        def interrupt(self) -> None:
            return None  # pragma: no cover

    class MockExecuteInstance(ExecuteInstance):
        def __init__(
            self,
            request: ExecuteRequest,
            options: ExecuteOptions,
            out: SyncWrite,
            err: SyncWrite,
            exit_code: int,
        ) -> None:
            super().__init__(request, options, out, err)
            self.exit_code = exit_code

        def __enter__(self) -> ExecuteStatus:
            return MockExecuteStatus(self.options, self._out, self._err, self.exit_code)

        def __exit__(
            self,
            exc_type: Optional[BaseException],  # noqa: U100
            exc_val: Optional[BaseException],  # noqa: U100
            exc_tb: Optional[TracebackType],  # noqa: U100
        ) -> None:
            pass

        @property
        def cmd(self) -> Sequence[str]:
            return self.request.cmd

    shell_cmds = []
    no_mocked_run_ids = getattr(request, "param", None)
    if no_mocked_run_ids is None:
        no_mocked_run_ids = ["_get_python"]
    original_execute_instance_factor = CondaEnvRunner._execute_instance_factory

    def mock_execute_instance_factory(
        request: ExecuteRequest, options: ExecuteOptions, out: SyncWrite, err: SyncWrite
    ):
        shell_cmds.append(request.shell_cmd)

        if request.run_id not in no_mocked_run_ids:
            return MockExecuteInstance(request, options, out, err, 0)
        else:
            return original_execute_instance_factor(request, options, out, err)

    monkeypatch.setattr(CondaEnvRunner, "_execute_instance_factory", mock_execute_instance_factory)
    monkeypatch.setenv("CONDA_EXE", "conda")
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "test-env")

    yield shell_cmds
