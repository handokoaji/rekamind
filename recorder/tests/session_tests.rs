mod common;
use common::{peak, read_wav};
use rekamind_recorder::backend::synthetic::{Script, SyntheticBackend};
use rekamind_recorder::session::{find_unfinished, recover_dir, Session, StartError, MARKER};
use rekamind_recorder::sink::SourceState;
use rekamind_recorder::timeline::Pacer;
use rekamind_recorder::Source;
use std::time::{Duration, Instant};

fn both() -> [Source; 2] {
    Source::ALL
}
fn wait_ms(ms: u64) {
    std::thread::sleep(Duration::from_millis(ms));
}

#[test]
fn records_both_sources_to_valid_equal_length_wavs() {
    let d = tempfile::tempdir().unwrap();
    let b = SyntheticBackend::new(
        Script {
            active_ms: 1500,
            ..Default::default()
        },
        Script {
            hz: 660.0,
            active_ms: 1500,
            amplitude: 0.5,
            ..Default::default()
        },
    );
    let s = Session::start(&b, d.path(), &both()).unwrap();
    wait_ms(400);
    let fin = s.stop();
    assert!(fin.warnings.is_empty(), "{:?}", fin.warnings);
    assert_eq!(fin.files.len(), 2);
    let mic = read_wav(&d.path().join("mic.wav"));
    let spk = read_wav(&d.path().join("speaker.wav"));
    assert_eq!(
        mic.samples.len(),
        spk.samples.len(),
        "both files must end together so the timeline lines up"
    );
    assert!(
        peak(&spk.samples) > peak(&mic.samples),
        "speaker is louder in this script"
    );
    assert!(peak(&mic.samples) > 8000);
    assert!(std::fs::read_to_string(d.path().join(MARKER))
        .unwrap()
        .contains("\"complete\""));
}

#[test]
fn a_silent_loopback_still_produces_a_file_as_long_as_the_meeting() {
    let d = tempfile::tempdir().unwrap();
    // Speaker produces nothing at all (computer silent); mic talks for 1.2 s.
    let b = SyntheticBackend::new(
        Script {
            active_ms: 1200,
            ..Default::default()
        },
        Script {
            active_ms: 0,
            ..Default::default()
        },
    );
    let s = Session::start(&b, d.path(), &both()).unwrap();
    wait_ms(1300);
    let fin = s.stop();
    let mic = read_wav(&d.path().join("mic.wav"));
    let spk = read_wav(&d.path().join("speaker.wav"));
    assert_eq!(spk.samples.len(), mic.samples.len());
    assert!(spk.samples.iter().all(|s| *s == 0), "padding is silence");
    assert_eq!(fin.files.len(), 2);
}

#[test]
fn a_source_that_cannot_open_does_not_stop_the_other_and_the_user_is_told() {
    let d = tempfile::tempdir().unwrap();
    let b = SyntheticBackend::new(
        Script {
            unavailable: Some("tidak ada mikrofon yang aktif".into()),
            ..Default::default()
        },
        Script {
            active_ms: 800,
            ..Default::default()
        },
    );
    let s = Session::start(&b, d.path(), &both()).unwrap();
    let st = s.status();
    assert!(matches!(&st.sources[0].state, SourceState::Unavailable(m) if m.contains("mikrofon")));
    assert_eq!(st.sources[1].state, SourceState::Recording);
    wait_ms(200);
    let fin = s.stop();
    assert!(
        fin.warnings
            .iter()
            .any(|w| w.contains("Mikrofon") && w.contains("tidak ada mikrofon")),
        "{:?}",
        fin.warnings
    );
    assert_eq!(
        fin.files.iter().map(|f| f.0).collect::<Vec<_>>(),
        vec![Source::Speaker]
    );
    assert!(
        !d.path().join("mic.wav").exists(),
        "no empty file left behind for the uploader to trip on"
    );
}

#[test]
fn nothing_openable_is_a_clear_error_not_an_empty_recording() {
    let d = tempfile::tempdir().unwrap();
    let u = |m: &str| Script {
        unavailable: Some(m.into()),
        ..Default::default()
    };
    match Session::start(&SyntheticBackend::new(u("a"), u("b")), d.path(), &both()) {
        Err(StartError::NothingToRecord(why)) => assert_eq!(why.len(), 2),
        other => panic!("expected NothingToRecord, got {:?}", other.map(|_| ())),
    }
}

#[test]
fn a_device_dying_mid_meeting_keeps_what_was_captured_and_the_other_source_continues() {
    let d = tempfile::tempdir().unwrap();
    let b = SyntheticBackend::new(
        Script {
            active_ms: 3000,
            fail_after_ms: Some(400),
            ..Default::default()
        },
        Script {
            active_ms: 3000,
            ..Default::default()
        },
    );
    let s = Session::start(&b, d.path(), &both()).unwrap();
    wait_ms(700);
    let st = s.status();
    assert!(
        matches!(st.sources[0].state, SourceState::Failed(_)),
        "{:?}",
        st.sources[0].state
    );
    assert_eq!(st.sources[1].state, SourceState::Recording);
    let fin = s.stop();
    assert!(fin.warnings.iter().any(|w| w.contains("Mikrofon")));
    let mic = read_wav(&d.path().join("mic.wav"));
    assert!(
        mic.samples.len() >= 16000 * 4 / 10,
        "audio before the failure is kept: {}",
        mic.samples.len()
    );
    assert!(peak(&mic.samples) > 5000);
}

#[test]
fn status_reports_levels_and_progress_for_the_ui() {
    let d = tempfile::tempdir().unwrap();
    let b = SyntheticBackend::new(
        Script {
            active_ms: 2000,
            realtime: true,
            ..Default::default()
        },
        Script {
            active_ms: 0,
            ..Default::default()
        },
    );
    let s = Session::start(&b, d.path(), &both()).unwrap();
    wait_ms(300);
    let first = s.status();
    assert!(
        first.sources[0].level > 0.1 && first.sources[0].level <= 1.0,
        "mic is audible: {}",
        first.sources[0].level
    );
    assert!(first.sources[0].seconds > 0.1);
    assert_eq!(
        first.sources[1].level, 0.0,
        "silent computer audio shows no level"
    );
    let again = s.status();
    assert!(again.sources[0].seconds >= first.sources[0].seconds);
    s.stop();
}

#[test]
fn an_unfinished_meeting_is_found_and_repaired_after_a_crash() {
    let root = tempfile::tempdir().unwrap();
    let live = root.path().join("rapat-1");
    let b = SyntheticBackend::new(
        Script {
            active_ms: 6000,
            realtime: true,
            ..Default::default()
        },
        Script {
            active_ms: 6000,
            realtime: true,
            ..Default::default()
        },
    );
    let s = Session::start(&b, &live, &both()).unwrap();
    wait_ms(2600); // past the first checkpoint
                   // "Power cut": copy the folder as it is right now and never stop the session in the copy.
    let crashed = root.path().join("rapat-crashed");
    std::fs::create_dir_all(&crashed).unwrap();
    for e in std::fs::read_dir(&live).unwrap() {
        let e = e.unwrap();
        std::fs::copy(e.path(), crashed.join(e.file_name())).unwrap();
    }
    s.stop();

    let found = find_unfinished(root.path());
    assert_eq!(
        found,
        vec![crashed.clone()],
        "only the crashed one is unfinished"
    );
    let rec = recover_dir(&crashed).unwrap();
    assert_eq!(rec.len(), 2);
    for (p, r) in rec {
        assert!(
            r.samples >= 16000,
            "{} recovered {} samples",
            p.display(),
            r.samples
        );
        read_wav(&p); // strictly valid after repair
    }
    assert!(
        find_unfinished(root.path()).is_empty(),
        "marked complete after recovery"
    );
}

#[test]
fn pacer_inserts_silence_only_for_real_gaps() {
    let t0 = Instant::now();
    let mut p = Pacer::new(t0, 16000);
    let at = |ms: u64| t0 + Duration::from_millis(ms);
    assert_eq!(p.gap(at(50)), 0, "jitter is not a gap");
    assert_eq!(
        p.gap(at(1000)),
        16000,
        "one second behind -> one second of silence"
    );
    p.wrote(16000);
    assert_eq!(p.gap(at(1000)), 0);
    p.wrote(8000); // ahead of the clock
    assert_eq!(p.gap(at(1200)), 0);
    assert_eq!(p.expected(at(2000)), 32000);
}
