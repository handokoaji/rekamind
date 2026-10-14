use rekamind_recorder::settings::{normalize_server, BackendEnv, Settings, UI_ORIGINS};
use std::path::Path;

fn env<'a>(dir: &'a Path, bundled: Option<&'a Path>) -> BackendEnv<'a> {
    BackendEnv {
        token: "t0k",
        data_dir: dir,
        engines_ready: false,
        llm_api_key: None,
        hf_token: None,
        bundled,
    }
}

#[test]
fn only_http_and_https_origins_are_accepted_and_paths_are_dropped() {
    assert_eq!(
        normalize_server("https://rekamind.kantor.id/api?x=1").as_deref(),
        Some("https://rekamind.kantor.id")
    );
    assert_eq!(
        normalize_server("  http://10.0.0.5:8787/ ").as_deref(),
        Some("http://10.0.0.5:8787")
    );
    for bad in [
        "",
        "rekamind.kantor.id",
        "ftp://x",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://",
        "http://user:pw@host",
        "http://a b",
    ] {
        assert_eq!(normalize_server(bad), None, "{bad:?} must be rejected");
    }
}

#[test]
fn remote_mode_needs_a_valid_server_and_local_mode_does_not() {
    let remote = Settings {
        mode: "remote".into(),
        server: "bukan url".into(),
        ..Default::default()
    };
    assert!(remote.validated().unwrap_err().contains("http"));
    let ok = Settings {
        mode: "remote".into(),
        server: "https://x.id/path".into(),
        ..Default::default()
    }
    .validated()
    .unwrap();
    assert_eq!(ok.server_url(), "https://x.id");
    assert_eq!(
        Settings::default().validated().unwrap().server_url(),
        "http://127.0.0.1:8787"
    );
}

#[test]
fn bad_values_are_refused_with_a_message() {
    assert!(Settings {
        mode: "cloud".into(),
        ..Default::default()
    }
    .validated()
    .is_err());
    assert!(Settings {
        local_port: 80,
        ..Default::default()
    }
    .validated()
    .is_err());
    assert!(Settings {
        language: "xx".into(),
        ..Default::default()
    }
    .validated()
    .is_err());
    assert!(Settings {
        local_program: "  ".into(),
        ..Default::default()
    }
    .validated()
    .is_err());
    assert!(Settings {
        hotkey: "".into(),
        ..Default::default()
    }
    .validated()
    .is_err());
}

#[test]
fn the_name_is_trimmed_and_capped() {
    let s = Settings {
        local_user_name: format!("  {}  ", "a".repeat(300)),
        ..Default::default()
    }
    .validated()
    .unwrap();
    assert_eq!(s.local_user_name.len(), 100);
}

#[test]
fn config_and_local_backend_follow_the_mode() {
    let local = Settings::default();
    assert_eq!(
        local.to_config(None).server.as_deref(),
        Some("http://127.0.0.1:8787")
    );
    assert!(local.local_backend(&env(Path::new("/d"), None)).is_some());
    let remote = Settings {
        mode: "remote".into(),
        server: "https://x.id".into(),
        local_user_name: "Andi".into(),
        ..Default::default()
    };
    assert_eq!(
        remote.to_config(None).server.as_deref(),
        Some("https://x.id")
    );
    assert_eq!(
        remote.to_config(None).local_user_name.as_deref(),
        Some("Andi")
    );
    assert!(
        remote.local_backend(&env(Path::new("/d"), None)).is_none(),
        "a remote server is never started or stopped by this app"
    );
}

#[test]
fn the_ui_origins_the_local_backend_must_allow_cover_every_webview() {
    for o in [
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ] {
        assert!(UI_ORIGINS.contains(o));
    }
}

#[test]
fn save_load_round_trips_and_a_corrupt_file_falls_back_to_defaults() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("cfg/settings.json");
    let s = Settings {
        mode: "remote".into(),
        server: "https://x.id".into(),
        local_user_name: "Andi".into(),
        auto_process: false,
        ..Default::default()
    };
    s.save(&p).unwrap();
    assert_eq!(Settings::load(&p), s);
    assert!(
        !p.with_extension("json.tmp").exists(),
        "temp file renamed away"
    );

    std::fs::write(&p, "{ this is not json").unwrap();
    assert_eq!(Settings::load(&p), Settings::default());
    std::fs::write(&p, r#"{"mode":"remote","server":"ftp://nope"}"#).unwrap();
    assert_eq!(
        Settings::load(&p),
        Settings::default(),
        "invalid values never leak in from disk"
    );
    assert_eq!(
        Settings::load(&d.path().join("missing.json")),
        Settings::default()
    );
}

#[test]
fn unknown_and_missing_fields_in_an_old_file_are_tolerated() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("s.json");
    std::fs::write(&p, r#"{"language":"en","some_future_field":1}"#).unwrap();
    let s = Settings::load(&p);
    assert_eq!((s.language.as_str(), s.local_port), ("en", 8787));
}

fn get<'a>(v: &'a [(String, String)], k: &str) -> Option<&'a str> {
    v.iter().find(|(a, _)| a == k).map(|(_, b)| b.as_str())
}

#[test]
fn auto_uses_the_bundled_backend_and_falls_back_to_python_in_development() {
    let s = Settings::default();
    assert_eq!(s.local_program, "auto");
    let bundled = Path::new("/opt/rekamind/backend/rekamind-backend");
    let (prog, args, engines) = s.launch(Some(bundled));
    assert_eq!(prog, bundled.to_string_lossy());
    assert!(args.is_empty() && engines == ["engines"]);
    let (prog, args, engines) = s.launch(None);
    assert_eq!(prog, "python");
    assert_eq!(args, ["-m", "rekamind_server"]);
    assert_eq!(engines, ["-m", "rekamind_server.enginepack"]);
    // an explicit program is never second-guessed
    let custom = Settings {
        local_program: "/usr/bin/py".into(),
        local_args: vec!["x.py".into()],
        ..Default::default()
    };
    assert_eq!(custom.launch(Some(bundled)).0, "/usr/bin/py");
}

#[test]
fn the_backend_environment_carries_the_secret_the_pack_and_processing_choices() {
    let d = Path::new("/data/rekamind");
    let s = Settings {
        whisper_model: "medium".into(),
        diarizer: "pyannote".into(),
        ..Default::default()
    };
    let e = BackendEnv {
        engines_ready: true,
        llm_api_key: Some("gsk_x"),
        hf_token: Some("hf_y"),
        ..env(d, None)
    };
    let v = s.backend_env(&e);
    assert_eq!(get(&v, "REKAMIND_AUTH"), Some("local_token"));
    assert_eq!(get(&v, "REKAMIND_LOCAL_TOKEN"), Some("t0k"));
    assert_eq!(get(&v, "REKAMIND_HOST"), Some("127.0.0.1"));
    assert_eq!(get(&v, "REKAMIND_ENGINES"), Some("local"));
    assert_eq!(get(&v, "REKAMIND_WHISPER_MODEL"), Some("medium"));
    assert_eq!(get(&v, "REKAMIND_DIARIZER"), Some("pyannote"));
    assert_eq!(get(&v, "REKAMIND_LLM_API_KEY"), Some("gsk_x"));
    assert_eq!(get(&v, "REKAMIND_HF_TOKEN"), Some("hf_y"));
    assert!(get(&v, "REKAMIND_ENGINE_PACK")
        .unwrap()
        .ends_with("engine-pack"));
    assert!(get(&v, "HF_HOME").unwrap().ends_with("models"));
    assert_eq!(get(&v, "REKAMIND_DATA_DIR"), Some("/data/rekamind"));
    // without the pack the backend must refuse to process, not crash on a missing import
    let none = s.backend_env(&env(d, None));
    assert_eq!(get(&none, "REKAMIND_ENGINES"), Some("none"));
    assert!(
        get(&none, "REKAMIND_LLM_API_KEY").is_none() && get(&none, "REKAMIND_HF_TOKEN").is_none()
    );
    // an empty secret is "not set", never an empty variable that shadows a real one
    let empty = s.backend_env(&BackendEnv {
        llm_api_key: Some(""),
        ..env(d, None)
    });
    assert!(get(&empty, "REKAMIND_LLM_API_KEY").is_none());
}

#[test]
fn processing_choices_are_validated() {
    let bad = |f: &dyn Fn(&mut Settings)| {
        let mut s = Settings::default();
        f(&mut s);
        s.validated().is_err()
    };
    assert!(bad(&|s| s.whisper_device = "tpu".into()));
    assert!(bad(&|s| s.diarizer = "magic".into()));
    assert!(bad(&|s| s.whisper_model = "  ".into()));
    assert!(bad(&|s| s.llm_model = String::new()));
    assert!(bad(&|s| s.llm_base_url = "file:///etc".into()));
    assert!(bad(&|s| s.llm_base_url = "https://u:p@h/v1".into()));
    let ok = Settings {
        llm_base_url: " http://localhost:11434/v1/ ".into(),
        ..Default::default()
    }
    .validated()
    .unwrap();
    assert_eq!(ok.llm_base_url, "http://localhost:11434/v1");
}

#[test]
fn an_old_settings_file_without_the_new_fields_still_loads_and_keeps_its_choices() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("settings.json");
    std::fs::write(&p, r#"{"mode":"local","local_program":"python","local_args":["-m","rekamind_server"],"local_port":9000}"#).unwrap();
    let s = Settings::load(&p);
    assert_eq!((s.local_port, s.local_program.as_str()), (9000, "python"));
    assert_eq!(s.whisper_model, "large-v3");
}
