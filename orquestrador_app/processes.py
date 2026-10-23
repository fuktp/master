from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from typing import Any

import psutil


def command(*arguments: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    return [sys.executable, "-B", "-m", "orquestrador_app", *arguments]


def spawn(arguments: list[str], **kwargs: Any) -> subprocess.Popen[Any]:
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(arguments, shell=False, **kwargs)


class OwnedTree:
    def __init__(self, process: subprocess.Popen[Any]):
        self.process = process
        self.identities: dict[int, float] = {}
        self.job: Any = None
        self.process_group: int | None = None
        if sys.platform != "win32":
            with contextlib.suppress(ProcessLookupError):
                if os.getpgid(process.pid) == process.pid:
                    self.process_group = process.pid
        if sys.platform == "win32":
            try:
                self.job = WindowsJob(process)
            except Exception:
                process.terminate()
                process.wait(timeout=5)
                raise
        self.capture()

    def capture(self) -> None:
        try:
            root = psutil.Process(self.process.pid)
            for child in [root, *root.children(recursive=True)]:
                self.identities.setdefault(child.pid, child.create_time())
        except psutil.Error:
            pass

    def stop(self, grace: float = 2) -> None:
        self.capture()
        if sys.platform != "win32" and self.process_group is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process_group, signal.SIGTERM)
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=grace)
        owned = []
        for pid, birth in self.identities.items():
            try:
                process = psutil.Process(pid)
                if process.create_time() == birth:
                    owned.append(process)
                    process.terminate()
            except psutil.Error:
                continue
        _, alive = psutil.wait_procs(owned, timeout=grace)
        for process in alive:
            try:
                process.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(alive, timeout=grace)
        if sys.platform != "win32" and self.process_group is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process_group, signal.SIGKILL)
        if self.job:
            self.job.close()
            self.job = None


def wait_for_exit(pid: int, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    return not psutil.pid_exists(pid)


class WindowsJob:
    """Kill-on-close ownership of this worker's descendants, including orphaned browser children."""

    def __init__(self, process: subprocess.Popen[Any]):
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("min_ws", ctypes.c_size_t),
                ("max_ws", ctypes.c_size_t),
                ("process_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Counters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "read_ops",
                    "write_ops",
                    "other_ops",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", Counters),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        self.kernel: Any = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("Não foi possível criar o Job Object da execução.")
        info = Extended()
        info.basic.flags = 0x00002000
        if not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ) or not self.kernel.AssignProcessToJobObject(
            self.handle, wintypes.HANDLE(int(getattr(process, "_handle")))
        ):
            self.close()
            raise OSError("Não foi possível proteger os subprocessos próprios no Windows.")

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
