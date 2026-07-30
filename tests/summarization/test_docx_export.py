from datetime import datetime

from docx import Document

from app.summarization.docx_export import export_mom_docx
from app.summarization.groq_client import MomResult


def test_export_creates_docx_with_expected_sections(tmp_path):
    mom = MomResult(
        minute_by_minute=[{"time": "00:00", "point": "Pembukaan"}],
        decisions=["Lanjutkan rencana A"],
        action_items=[{"item": "Kirim laporan", "assignee": "Budi", "due": "2026-08-01"}],
        detailed_notes="Semua peserta setuju melanjutkan.",
    )
    output_path = tmp_path / "mom.docx"

    result_path = export_mom_docx("Rapat Mingguan", datetime(2026, 7, 30, 9, 0), mom, output_path)

    assert result_path == output_path
    assert output_path.exists()

    doc = Document(str(output_path))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Rapat Mingguan" in full_text
    assert "Ringkasan Menit ke Menit" in full_text
    assert "Keputusan" in full_text
    assert "Action Items" in full_text
    assert "Catatan Detail" in full_text
    assert "Lanjutkan rencana A" in full_text
    assert "Semua peserta setuju melanjutkan." in full_text
