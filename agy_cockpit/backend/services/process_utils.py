"""Own subprocess groups/jobs so cancellation also reaps descendant workers."""
import asyncio
import os
import signal
import subprocess
import weakref

_jobs = weakref.WeakKeyDictionary()


def _windows_job(process):
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    class Basic(ctypes.Structure):
        _fields_ = [('user_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', w.DWORD),
                    ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('active', w.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
    class Io(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', Io), ('process_limit', ctypes.c_size_t), ('job_limit', ctypes.c_size_t),
                    ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]; kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job: raise ctypes.WinError(ctypes.get_last_error())
    handle = None
    try:
        info = Extended(); info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        handle = kernel.OpenProcess(0x100 | 0x1 | 0x800 | 0x1000, False, process.pid)
        if not handle or not kernel.AssignProcessToJobObject(job, handle):
            raise ctypes.WinError(ctypes.get_last_error())
        # The process was created suspended; assigning before resume closes the child-spawn race.
        resume = ctypes.WinDLL('ntdll').NtResumeProcess
        resume.argtypes = [w.HANDLE]; resume.restype = ctypes.c_long
        if resume(handle) != 0: raise RuntimeError('Could not resume owned worker')
        _jobs[process] = (job, kernel)
    except BaseException:
        kernel.CloseHandle(job)
        raise
    finally:
        if handle: kernel.CloseHandle(handle)


async def spawn_owned_process(*args, **kwargs):
    if os.name == 'nt':
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x4 | subprocess.CREATE_NO_WINDOW
    else:
        kwargs['start_new_session'] = True
    process = await asyncio.create_subprocess_exec(*args, **kwargs)
    if os.name == 'nt':
        try:
            _windows_job(process)
        except BaseException:
            process.kill(); await process.wait(); raise
    return process


async def terminate_process_tree(process):
    job = _jobs.pop(process, None)
    if job:
        handle, kernel = job
        kernel.CloseHandle(handle)  # Kills descendants even if their parent has exited.
    elif os.name != 'nt':
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
            elif process.returncode is None:
                process.kill()
        except ProcessLookupError:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
    elif process.returncode is None:
        await asyncio.to_thread(subprocess.run, ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=3)
    if process.returncode is None:
        try: process.kill()
        except ProcessLookupError: pass
    await process.wait()
