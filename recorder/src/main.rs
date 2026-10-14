use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use rekamind_recorder::api::Client;
use rekamind_recorder::backend::synthetic::{Script, SyntheticBackend};
use rekamind_recorder::session::{self, Finished, Session};
use rekamind_recorder::sink::SourceState;
use rekamind_recorder::uploader::{self, Meta};
use rekamind_recorder::{stats, Source};

const HELP: &str = "\
rekamind-rec: perekam rapat (mikrofon + audio komputer) yang ringan.

PEMAKAIAN
  rekamind-rec record  [opsi]        Rekam sampai Ctrl+C (atau --duration)
  rekamind-rec upload  FOLDER [opsi] Unggah rekaman yang sudah ada ke server
  rekamind-rec recover FOLDER        Perbaiki rekaman yang terhenti mendadak
  rekamind-rec login --server URL    Masuk dengan Google lewat browser (alat bantu; aplikasi desktop menyimpan token di penyimpanan aman OS)

OPSI record
  --out FOLDER        Folder induk rekaman (bawaan: ./rekamind-recordings)
  --duration DETIK    Berhenti otomatis
  --no-mic            Jangan rekam mikrofon
  --no-speaker        Jangan rekam audio komputer
  --stats             Tampilkan pemakaian CPU dan memori perekam sendiri
  --synthetic         Nada uji, tanpa perangkat audio (untuk percobaan)

OPSI record/upload (kirim ke server setelah selesai)
  --server URL        Alamat backend, mis. http://127.0.0.1:8787
  --token TOKEN       Token akses (bila server memintanya; hasil `login --print-token`)
  --title JUDUL       Judul rapat
  --name NAMA         Nama Anda (untuk mic)
  --lang id|en        Bahasa rekaman (bawaan: id)
  --process           Langsung proses setelah diunggah

OPSI login
  --no-browser        Cetak alamat login saja, jangan buka browser
  --print-token       Cetak token ke stdout (untuk skrip/CI; perlakukan seperti kata sandi)

Rekaman selalu disimpan di disk lebih dulu; kegagalan unggah tidak menghilangkan rekaman.
";

#[derive(Default)]
struct Opts {
    out: Option<PathBuf>,
    dir: Option<PathBuf>,
    duration: Option<u64>,
    no_mic: bool,
    no_speaker: bool,
    show_stats: bool,
    synthetic: bool,
    server: Option<String>,
    token: Option<String>,
    title: Option<String>,
    name: Option<String>,
    lang: Option<String>,
    process: bool,
    no_browser: bool,
    print_token: bool,
}

fn parse(args: Vec<String>) -> Result<(String, Opts), lexopt::Error> {
    use lexopt::prelude::*;
    let mut p = lexopt::Parser::from_args(args);
    let mut o = Opts::default();
    let mut cmd = None;
    while let Some(a) = p.next()? {
        match a {
            Value(v) if cmd.is_none() => cmd = Some(v.string()?),
            Value(v) if o.dir.is_none() => o.dir = Some(PathBuf::from(v)),
            Long("out") => o.out = Some(p.value()?.into()),
            Long("duration") => o.duration = Some(p.value()?.parse()?),
            Long("no-mic") => o.no_mic = true,
            Long("no-speaker") => o.no_speaker = true,
            Long("stats") => o.show_stats = true,
            Long("synthetic") => o.synthetic = true,
            Long("server") => o.server = Some(p.value()?.string()?),
            Long("token") => o.token = Some(p.value()?.string()?),
            Long("title") => o.title = Some(p.value()?.string()?),
            Long("name") => o.name = Some(p.value()?.string()?),
            Long("lang") => o.lang = Some(p.value()?.string()?),
            Long("process") => o.process = true,
            Long("no-browser") => o.no_browser = true,
            Long("print-token") => o.print_token = true,
            Short('h') | Long("help") => return Ok(("help".into(), o)),
            _ => return Err(a.unexpected()),
        }
    }
    Ok((cmd.unwrap_or_else(|| "help".into()), o))
}

fn bar(level: f32) -> char {
    const B: [char; 8] = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];
    B[((level.sqrt() * 7.99) as usize).min(7)]
}

fn clock(d: Duration) -> String {
    let s = d.as_secs();
    format!("{:02}:{:02}:{:02}", s / 3600, s % 3600 / 60, s % 60)
}

fn new_dir(root: &Path) -> PathBuf {
    let mut b = [0u8; 2];
    let _ = getrandom::fill(&mut b);
    let t = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    root.join(format!("rapat-{t}-{:02x}{:02x}", b[0], b[1]))
}

fn upload(dir: &Path, files: &[(Source, PathBuf)], o: &Opts) -> Result<(), String> {
    let server = o.server.as_deref().ok_or("--server diperlukan")?;
    let client = Client::new(server, o.token.clone());
    let meta = Meta {
        title: o.title.clone().unwrap_or_else(|| {
            dir.file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_else(|| "Rapat".into())
        }),
        language: o.lang.clone().unwrap_or_else(|| "id".into()),
        local_user_name: o.name.clone(),
        process: o.process,
    };
    let mut last_step = "";
    let id = uploader::upload_meeting(
        &client,
        files,
        &meta,
        |p| {
            if p.step != last_step {
                last_step = p.step;
                eprintln!("  {}", p.step);
            }
        },
        std::thread::sleep,
    )?;
    eprintln!(
        "Selesai diunggah. ID rapat: {id}{}",
        if o.process { " (sedang diproses)" } else { "" }
    );
    Ok(())
}

fn report_and_upload(fin: &Finished, o: &Opts) -> ExitCode {
    eprintln!(
        "\nTersimpan di {} ({})",
        fin.dir.display(),
        clock(fin.duration)
    );
    for w in &fin.warnings {
        eprintln!("  ! {w}");
    }
    if fin.files.is_empty() {
        eprintln!("Tidak ada audio yang terekam.");
        return ExitCode::from(1);
    }
    if o.server.is_some() {
        if let Err(e) = upload(&fin.dir, &fin.files, o) {
            eprintln!("\nGagal mengunggah: {e}\nRekaman AMAN di disk. Coba lagi nanti dengan:\n  rekamind-rec upload \"{}\" --server <URL> --title \"<judul>\"", fin.dir.display());
            return ExitCode::from(2);
        }
    }
    ExitCode::SUCCESS
}

fn record(o: Opts) -> ExitCode {
    let root = o
        .out
        .clone()
        .unwrap_or_else(|| PathBuf::from("rekamind-recordings"));
    let dir = new_dir(&root);
    let want: Vec<Source> = Source::ALL
        .into_iter()
        .filter(|s| !(o.no_mic && *s == Source::Mic) && !(o.no_speaker && *s == Source::Speaker))
        .collect();
    let backend: Box<dyn rekamind_recorder::backend::Backend> = if o.synthetic {
        let s = Script {
            realtime: true,
            active_ms: u64::MAX,
            ..Script::default()
        };
        Box::new(SyntheticBackend::new(
            Script {
                hz: 440.0,
                ..s.clone()
            },
            Script { hz: 660.0, ..s },
        ))
    } else {
        rekamind_recorder::backend::default_backend()
    };

    let session = match Session::start(backend.as_ref(), &dir, &want) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Gagal mulai merekam: {e}");
            return ExitCode::from(1);
        }
    };
    let stop = Arc::new(AtomicBool::new(false));
    let flag = stop.clone();
    let _ = ctrlc::set_handler(move || flag.store(true, Ordering::Relaxed));
    eprintln!(
        "Merekam ke {} . Tekan Ctrl+C untuk berhenti.",
        dir.display()
    );

    let started = std::time::Instant::now();
    let mut told: Vec<(Source, SourceState)> = Vec::new();
    while !stop.load(Ordering::Relaxed)
        && o.duration.is_none_or(|d| started.elapsed().as_secs() < d)
    {
        std::thread::sleep(Duration::from_millis(500));
        let st = session.status();
        let mut line = format!("\r● {} ", clock(st.elapsed));
        for s in &st.sources {
            line += &format!(" {} {}", s.source.label(), bar(s.level));
            if !told
                .iter()
                .any(|(src, state)| *src == s.source && *state == s.state)
                && s.state != SourceState::Recording
            {
                eprintln!("\n  ! {}: {:?}", s.source.label(), s.state);
                told.retain(|(src, _)| *src != s.source);
                told.push((s.source, s.state.clone()));
            }
        }
        eprint!("{line}   ");
    }
    let fin = session.stop();
    if o.show_stats {
        if let Some(u) = stats::usage() {
            let wall = fin.duration.as_secs_f64().max(0.001);
            eprintln!("\n[stats] CPU: {:.2}% rata-rata ({:.2} dtk CPU dalam {:.0} dtk) · memori puncak: {:.1} MB", u.cpu_seconds / wall * 100.0, u.cpu_seconds, wall, u.peak_rss_mb);
        }
    }
    report_and_upload(&fin, &o)
}

fn main() -> ExitCode {
    let (cmd, o) = match parse(std::env::args().skip(1).collect()) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("{e}\n\n{HELP}");
            return ExitCode::from(1);
        }
    };
    match cmd.as_str() {
        "record" => record(o),
        "login" => {
            let Some(server) = o.server.clone() else {
                eprintln!("Sebutkan --server.\n\n{HELP}");
                return ExitCode::from(1);
            };
            let pending = match rekamind_recorder::login::PendingLogin::begin(&server) {
                Ok(p) => p,
                Err(e) => {
                    eprintln!("Tidak bisa membuka port lokal untuk login: {e}");
                    return ExitCode::from(1);
                }
            };
            eprintln!("Buka alamat ini di browser untuk masuk:\n  {}", pending.url);
            if !o.no_browser {
                let _ = webbrowser::open(&pending.url);
            }
            let code = match pending.wait_for_code(Duration::from_secs(300)) {
                Ok(c) => c,
                Err(e) => {
                    eprintln!("{e}");
                    return ExitCode::from(2);
                }
            };
            match Client::new(&server, None).desktop_token(&code, &pending.verifier) {
                Ok(t) => {
                    eprintln!("Berhasil masuk sebagai {}", t.email);
                    if o.print_token {
                        println!("{}", t.access_token);
                    }
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("Login gagal: {e}");
                    ExitCode::from(2)
                }
            }
        }
        "recover" => {
            let Some(dir) = o.dir else {
                eprintln!("Sebutkan folder rekaman.\n\n{HELP}");
                return ExitCode::from(1);
            };
            match session::recover_dir(&dir) {
                Ok(r) if r.is_empty() => {
                    eprintln!("Tidak ada file rekaman di {}", dir.display());
                    ExitCode::from(1)
                }
                Ok(r) => {
                    for (p, rec) in r {
                        eprintln!(
                            "{}: {:.1} dtk{}",
                            p.display(),
                            rec.samples as f64 / 16000.0,
                            if rec.repaired { " (diperbaiki)" } else { "" }
                        );
                    }
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("Gagal memperbaiki: {e}");
                    ExitCode::from(1)
                }
            }
        }
        "upload" => {
            let Some(dir) = o.dir.clone() else {
                eprintln!("Sebutkan folder rekaman.\n\n{HELP}");
                return ExitCode::from(1);
            };
            let files: Vec<(Source, PathBuf)> = Source::ALL
                .into_iter()
                .map(|s| (s, dir.join(s.file_name())))
                .filter(|(_, p)| p.is_file())
                .collect();
            if files.is_empty() {
                eprintln!("Tidak ada mic.wav/speaker.wav di {}", dir.display());
                return ExitCode::from(1);
            }
            for (_, p) in &files {
                let _ = rekamind_recorder::wav::recover(p); // harmless on a clean file, fixes a crashed one
            }
            match upload(&dir, &files, &o) {
                Ok(()) => ExitCode::SUCCESS,
                Err(e) => {
                    eprintln!("Gagal: {e}");
                    ExitCode::from(2)
                }
            }
        }
        _ => {
            print!("{HELP}");
            ExitCode::SUCCESS
        }
    }
}
