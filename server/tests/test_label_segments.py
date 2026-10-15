"""Speaker labels per ASR segment: cut at speaker changes, nearest speaker in gaps, no flicker."""
from rekamind_server.engines.base import AsrSegment, SpeakerTurn
from rekamind_server.pipeline import label_segments


def words(*items):
    return tuple((a, b, w) for a, b, w in items)


A, B = SpeakerTurn(0, 3000, "SPEAKER_00"), SpeakerTurn(3000, 6000, "SPEAKER_01")


def test_a_sentence_spanning_two_speakers_is_cut_where_the_voice_changes():
    seg = AsrSegment(0, 6000, "Halo semua apa kabar baik terima kasih", words(
        (0, 500, " Halo"), (500, 1200, " semua"), (1200, 2400, " apa"), (2400, 2900, " kabar"),
        (3100, 3800, " baik"), (3800, 4500, " terima"), (4500, 5500, " kasih")))
    out = label_segments([seg], [A, B])
    assert [(lab, s.text) for s, lab in out] == [("SPEAKER_00", "Halo semua apa kabar"), ("SPEAKER_01", "baik terima kasih")]
    assert out[0][0].end_ms == 2900 and out[1][0].start_ms == 3100


def test_a_one_word_blip_of_another_speaker_does_not_split_the_sentence():
    turns = [SpeakerTurn(0, 1000, "SPEAKER_00"), SpeakerTurn(1000, 1300, "SPEAKER_01"), SpeakerTurn(1300, 3000, "SPEAKER_00")]
    seg = AsrSegment(0, 3000, "ini hanya satu kalimat panjang", words(
        (0, 400, " ini"), (400, 900, " hanya"), (1050, 1250, " satu"), (1500, 2200, " kalimat"), (2200, 3000, " panjang")))
    out = label_segments([seg], turns)
    assert len(out) == 1 and out[0][1] == "SPEAKER_00" and out[0][0].text == seg.text


def test_a_segment_in_a_gap_takes_the_nearest_speaker_not_unknown():
    out = label_segments([AsrSegment(3300, 3600, "ya")], [SpeakerTurn(0, 3000, "SPEAKER_00"), SpeakerTurn(9000, 12000, "SPEAKER_01")])
    assert [lab for _, lab in out] == ["SPEAKER_00"]


def test_unknown_only_when_no_speaker_is_anywhere_near():
    assert [lab for _, lab in label_segments([AsrSegment(50000, 51000, "x")], [A, B])] == ["UNKNOWN"]
    assert [lab for _, lab in label_segments([AsrSegment(0, 1000, "x")], [])] == ["UNKNOWN"]


def test_without_word_timing_the_speaker_with_most_overlap_wins_and_fallback_forces_one_label():
    seg = AsrSegment(2000, 6000, "campur")  # 1000 ms of A, 3000 ms of B
    assert [lab for _, lab in label_segments([seg], [A, B])] == ["SPEAKER_01"]
    assert [lab for _, lab in label_segments([seg], [A, B], fallback="SPEAKER_00")] == ["SPEAKER_00"]


def test_a_short_back_channel_inside_a_sentence_does_not_cut_it():
    # "gue hari" by the other voice for 0.6 s in the middle of one person's sentence (seen on real audio)
    turns = [SpeakerTurn(0, 1000, "SPEAKER_00"), SpeakerTurn(1000, 1600, "SPEAKER_02"), SpeakerTurn(1600, 4000, "SPEAKER_00")]
    seg = AsrSegment(0, 4000, "kristal enak itu gue hari ini agenda gue cuma satu", words(
        (0, 400, " kristal"), (400, 700, " enak"), (700, 950, " itu"), (1050, 1300, " gue"), (1300, 1550, " hari"),
        (1650, 2000, " ini"), (2000, 2500, " agenda"), (2500, 3000, " gue"), (3000, 3500, " cuma"), (3500, 4000, " satu")))
    out = label_segments([seg], turns)
    assert len(out) == 1 and out[0][1] == "SPEAKER_00"


def test_a_real_turn_of_three_words_and_a_second_still_cuts():
    seg = AsrSegment(0, 6000, "satu dua tiga empat lima enam", words(
        (0, 500, " satu"), (500, 1500, " dua"), (1500, 2900, " tiga"), (3100, 3700, " empat"), (3700, 4300, " lima"), (4300, 5000, " enam")))
    assert [lab for _, lab in label_segments([seg], [A, B])] == ["SPEAKER_00", "SPEAKER_01"]


def test_a_continuation_token_is_never_cut_from_its_word():
    seg = AsrSegment(0, 6000, "satu dua tiga empat coba-coba lima enam", words(
        (0, 500, " satu"), (500, 1500, " dua"), (1500, 2900, " tiga"), (2900, 3300, " coba"), (3300, 3700, "-coba"),
        (3700, 4300, " lima"), (4300, 5000, " enam"), (5000, 5800, " tujuh")))
    out = label_segments([seg], [SpeakerTurn(0, 3500, "SPEAKER_00"), SpeakerTurn(3500, 6000, "SPEAKER_01")])
    assert [s.text for s, _ in out] == ["satu dua tiga empat coba-coba", "lima enam tujuh"] or all("-coba" not in s.text.split()[0] for s, _ in out)
