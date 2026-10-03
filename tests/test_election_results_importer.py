import pytest
from openpyxl import Workbook

from app.services.election_results_importer import ElectionResultsImporter


def write_workbook(directory, cycle, sheets):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        worksheet = workbook.create_sheet(name)
        for row in rows:
            worksheet.append(row)
    workbook.save(directory / f"federalelections{cycle}.xlsx")
    workbook.close()


def congressional_rows(*, older=False, winner_column=21):
    # Column positions and labels taken from the actual 2010/2012 headers.
    headers = [None] * 24
    headers[1:5] = (
        ["STATE", "STATE ABBREVIATION", "DISTRICT", "FEC ID#"]
        if older else ["STATE ABBREVIATION", "STATE", "D", "FEC ID#"]
    )
    headers[8] = "CANDIDATE NAME (Last, First)" if older else "CANDIDATE NAME"
    headers[10] = "PARTY"
    headers[15:17] = ["GENERAL " if older else "GENERAL VOTES ", "GENERAL %"]
    headers[19 if older else 22] = "FOOTNOTES"
    if winner_column is not None:
        headers[winner_column] = "GE WINNER INDICATOR"
    rows = [headers]
    for candidate_id, district in (("H2AL01077", "01"), ("S6AL00013", "S"), ("n/a", "01")):
        row = [None] * 24
        row[1:5] = ["Alabama", "AL", district, candidate_id] if older else ["AL", "Alabama", district, candidate_id]
        row[8], row[10], row[15], row[16] = "Candidate, Test", "REP", 129063, 0.825
        row[19 if older else 22] = "A footnote, not a winner"
        if winner_column is not None:
            row[winner_column] = "W"
        rows.append(row)
    primary_only = rows[1].copy()
    primary_only[15] = None
    rows.append(primary_only)
    return rows


@pytest.mark.parametrize("cycle,name,older", [
    (2010, "2010 US House & Senate Results", True),
    (2012, "2012 US House & Senate Resuts", False),
    (2008, "2008 US House & Senate Results", True),
])
@pytest.mark.parametrize("office,candidate_id,district", [
    ("H", "H2AL01077", "01"), ("S", "S6AL00013", None),
])
def test_combined_sheets(tmp_path, cycle, name, older, office, candidate_id, district):
    write_workbook(tmp_path, cycle, {name: congressional_rows(older=older, winner_column=None if older else 21)})
    assert ElectionResultsImporter(str(tmp_path)).read_election_results(cycle, office) == [{
        "fec_candidate_id": candidate_id, "cycle": cycle, "state": "AL",
        "office": office, "district": district, "candidate_name": "Candidate, Test",
        "party": "REP", "general_votes": 129063, "general_percentage": 0.825,
        "general_winner": None if older else "W",
    }]


@pytest.mark.parametrize("office,title,index", [("H", "House", 1), ("S", "Senate", 2)])
@pytest.mark.parametrize("winner_column", [21, 22])
def test_separate_sheets_take_precedence(tmp_path, office, title, index, winner_column):
    rows = congressional_rows(winner_column=winner_column)
    write_workbook(tmp_path, 2022, {
        f"8. US {title} Results by State": [rows[0], rows[index]],
        "2022 US House & Senate Results": congressional_rows(older=True, winner_column=None),
    })
    results = ElectionResultsImporter(str(tmp_path)).read_election_results(2022, office)
    assert len(results) == 1
    assert results[0]["general_winner"] == "W"
    assert results[0]["state"] == "AL"


def test_missing_sheet_lists_available_names(tmp_path):
    write_workbook(tmp_path, 2010, {"Publication Information": [["Information"]]})
    with pytest.raises(ValueError, match="Available sheets:.*Publication Information"):
        ElectionResultsImporter(str(tmp_path)).read_election_results(2010, "H")


def test_combined_sheet_is_not_used_for_president(tmp_path):
    write_workbook(tmp_path, 2012, {"2012 US House & Senate Resuts": congressional_rows()})
    with pytest.raises(ValueError, match="Pres General Results.*Available sheets"):
        ElectionResultsImporter(str(tmp_path)).read_election_results(2012, "P")
