"""Локальный PostgreSQL для TimeBalance: поднимает и останавливает вместе с приложением.

Сервер берётся из пакета pgserver (бинарники внутри .venv) — без Docker и
установки в систему. Порт каждый раз новый и пишется в .env как DATABASE_URL.
"""
from __future__ import annotations

import os
import pathlib

import pgserver
import pgserver.postgres_server as _ps

# pg_ctl по умолчанию ждёт всего 10 секунд, а первый старт на Windows после
# принудительного убийства (восстановление + антивирус на файле лога) длиннее —
# поднимаем порог, чтобы не ловить ложный «Timeout starting server».
_orig_pg_ctl = _ps.pg_ctl


def _patient_pg_ctl(*args, **kwargs):
    kwargs["timeout"] = max(int(kwargs.get("timeout", 0) or 0), 90)
    return _orig_pg_ctl(*args, **kwargs)


_ps.pg_ctl = _patient_pg_ctl

ROOT = pathlib.Path(__file__).resolve().parent
PGDATA = ROOT / ".pgdata"
ENV_PATH = ROOT / ".env"


def _write_env(uri: str) -> None:
    if not ENV_PATH.exists():
        ENV_PATH.write_text(
            (ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
        )
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    out, found = [], False
    for line in lines:
        if line.startswith("DATABASE_URL="):
            out.append("DATABASE_URL=" + uri)
            found = True
        else:
            out.append(line)
    if not found:
        out.append("DATABASE_URL=" + uri)
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def _bind_job(srv) -> None:
    """Привязывает postgres к Job Object с флагом «убить при закрытии».

    Любое завершение приложения (Ctrl+C, остановка в PyCharm, убийство в
    диспетчере задач) закрывает ручку задания — и postgres исчезает вместе с ним.
    """
    import ctypes
    import ctypes.wintypes as wt

    try:
        pid = srv.get_pid()
        if not pid:
            return
        k32 = ctypes.windll.kernel32

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wt.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wt.DWORD),
                ("SchedulingClass", wt.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001

        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.CreateJobObjectW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
        k32.SetInformationJobObject.restype = wt.BOOL
        k32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD,
        ]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k32.AssignProcessToJobObject.restype = wt.BOOL
        k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]

        job = k32.CreateJobObjectW(None, None)
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise ctypes.WinError()
        handle = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not handle:
            raise ctypes.WinError()
        try:
            if not k32.AssignProcessToJobObject(job, handle):
                raise ctypes.WinError()
        finally:
            k32.CloseHandle(handle)
        # Ручка задания живёт до завершения процесса: её закрытие убьёт postgres.
        _JOB_HANDLES.append(job)
    except Exception as exc:  # noqa: BLE001 - страховка не должна ронять запуск
        print(f"предупреждение: postgres не привязан к процессу: {exc}")


_JOB_HANDLES: list = []


def ensure_server(*, cleanup_mode, die_with_process: bool = False) -> str:
    """Поднимает PostgreSQL (если не поднят) и возвращает DATABASE_URL.

    cleanup_mode="stop" — pgserver остановит сервер при штатном выходе процесса.
    die_with_process=True — дополнительная страховка через Job Object: postgres
    исчезает из диспетчера задач даже при жёстком завершении приложения.
    """
    srv = pgserver.get_server(str(PGDATA), cleanup_mode=cleanup_mode)
    try:
        srv.psql("CREATE DATABASE timebalance;")
    except Exception:  # noqa: BLE001 - база уже существует
        pass
    uri = srv.get_uri(database="timebalance")
    os.environ["DATABASE_URL"] = uri
    _write_env(uri)
    if die_with_process:
        _bind_job(srv)
    return uri
