//! The recorder measuring itself, so "lightweight" is a number anyone can check on their own
//! machine (`rekamind-rec record --stats`) instead of a claim.

#[derive(Debug, Clone, Copy)]
pub struct Usage {
    /// CPU seconds (user + kernel) consumed by this process so far.
    pub cpu_seconds: f64,
    /// Peak resident memory, MB.
    pub peak_rss_mb: f64,
}

#[cfg(unix)]
pub fn usage() -> Option<Usage> {
    // SAFETY: getrusage fills the zeroed struct we pass; RUSAGE_SELF is always valid.
    let ru = unsafe {
        let mut ru: libc::rusage = std::mem::zeroed();
        if libc::getrusage(libc::RUSAGE_SELF, &mut ru) != 0 {
            return None;
        }
        ru
    };
    let tv = |t: libc::timeval| t.tv_sec as f64 + t.tv_usec as f64 / 1e6;
    #[cfg(target_os = "macos")]
    let rss = ru.ru_maxrss as f64 / 1e6; // bytes on macOS
    #[cfg(not(target_os = "macos"))]
    let rss = ru.ru_maxrss as f64 / 1e3; // kilobytes on Linux
    Some(Usage {
        cpu_seconds: tv(ru.ru_utime) + tv(ru.ru_stime),
        peak_rss_mb: rss,
    })
}

#[cfg(windows)]
pub fn usage() -> Option<Usage> {
    use windows_sys::Win32::Foundation::FILETIME;
    use windows_sys::Win32::System::ProcessStatus::{
        K32GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS,
    };
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, GetProcessTimes};

    // SAFETY: all out-pointers reference live stack values of the exact types the API expects.
    unsafe {
        let p = GetCurrentProcess();
        let z = FILETIME {
            dwLowDateTime: 0,
            dwHighDateTime: 0,
        };
        let (mut c, mut e, mut k, mut u) = (z, z, z, z);
        if GetProcessTimes(p, &mut c, &mut e, &mut k, &mut u) == 0 {
            return None;
        }
        let ft =
            |f: FILETIME| ((f.dwHighDateTime as u64) << 32 | f.dwLowDateTime as u64) as f64 / 1e7; // 100 ns ticks
        let mut m: PROCESS_MEMORY_COUNTERS = std::mem::zeroed();
        m.cb = std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32;
        if K32GetProcessMemoryInfo(p, &mut m, m.cb) == 0 {
            return None;
        }
        Some(Usage {
            cpu_seconds: ft(k) + ft(u),
            peak_rss_mb: m.PeakWorkingSetSize as f64 / 1e6,
        })
    }
}
