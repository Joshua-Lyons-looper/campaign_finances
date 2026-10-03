import zipfile
import csv
from pathlib import Path
from decimal import Decimal

class FECBulkImporter:

    def __init__(self, data_directory: str = "data"):
        self.data_directory = Path(data_directory)

    def list_datasets(self) -> list[dict]:
        datasets = []

        for zip_path in self.data_directory.glob("*.zip"):

            with zipfile.ZipFile(zip_path, "r") as zip_file:
                datasets.append({
                    "zip_file": zip_path.name,
                    "contents": zip_file.namelist(),
                })

        return datasets

    def read_candidates(self,cycle: int,) -> list[dict]:
        zip_path = (
            self.data_directory / f"cn{str(cycle)[-2:]}.zip"
        )
        candidates = []
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            with zip_file.open("cn.txt") as file:
                lines = (
                    line.decode("utf-8")
                    for line in file
                )

                reader = csv.reader(
                    lines,
                    delimiter="|",
                )

                for row in reader:
                    #THESE INDEXES ARE NOT ARBITRARY, THEY ARE BASED ON THE FEC CANDIDATE FILE FORMAT
                    candidates.append({
                        "candidate_id": row[0],
                        "name": row[1],
                        "party": row[2],
                        "election_year": row[3],
                        "state": row[4],
                        "office": row[5],
                        "district": row[6],
                        "incumbent_challenger": row[7],
                        "candidate_status": row[8],
                        "principal_committee_id": row[9],
                    })

        return candidates


    def read_candidate_finances(self,cycle: int,) -> dict[str, dict]:

        zip_path = (
            self.data_directory / f"weball{str(cycle)[-2:]}.zip"
        )

        finances = {}

        with zipfile.ZipFile(zip_path, "r") as zip_file:

            filename = f"weball{str(cycle)[-2:]}.txt"

            with zip_file.open(filename) as file:
                lines = (
                    line.decode("utf-8")
                    for line in file
                )
                reader = csv.reader(
                    lines,
                    delimiter="|",
                )
                for row in reader:
                    candidate_id = row[0]

                    finances[candidate_id] = {
                    "candidate_id": candidate_id,
                    "name": row[1],
                    "receipts": Decimal(row[5] or "0"),
                    "disbursements": Decimal(row[7] or "0"),
                    "cash_on_hand": Decimal(row[10] or "0"),
                    "individual_contributions": Decimal(row[17] or "0"),
                    "other_committee_contributions": Decimal(row[25] or "0"),
                }
        return finances

    def read_independent_expenditures(self,cycle: int,) -> list[dict]:
        file_path = (
            self.data_directory
            / f"independent_expenditure_{cycle}.csv"
        )
        expenditures = []
        with file_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:

            reader = csv.DictReader(file)

            for row in reader:

                candidate_id = (
                    row["cand_id"].strip()
                    if row["cand_id"]
                    else None
                )

                support_oppose = (
                    row["sup_opp"].strip().upper()
                    if row["sup_opp"]
                    else None
                )

                amount = Decimal(
                    row["exp_amo"] or "0"
                )

                if not candidate_id:
                    continue

                if support_oppose not in {"S", "O"}:
                    continue

                expenditures.append({
                    "candidate_id": candidate_id,
                    "spender_id": (
                        row["spe_id"].strip()
                        if row["spe_id"]
                        else None
                    ),
                    "amount": amount,
                    "support_oppose": support_oppose,
                    "transaction_id": row["tran_id"],
                    "file_number": row["file_num"],
                    "previous_file_number": row["prev_file_num"],
                    "amendment_indicator": row["amndt_ind"],
                })

        return expenditures

    def read_current_independent_expenditures(self,cycle: int,) -> list[dict]:

        expenditures = self.read_independent_expenditures(
            cycle=cycle,
        )

        superseded_file_numbers = {
            expenditure["previous_file_number"]
            for expenditure in expenditures
            if expenditure["previous_file_number"]
        }

        current_expenditures = [
            expenditure
            for expenditure in expenditures
            if expenditure["file_number"]
            not in superseded_file_numbers
        ]

        return current_expenditures

    def read_independent_expenditure_totals(self,cycle: int,) -> dict[str, dict]:
        expenditures = (
            self.read_current_independent_expenditures(
                cycle=cycle,
            )
        )
        totals = {}

        for expenditure in expenditures:
            candidate_id = expenditure["candidate_id"]
            amount = expenditure["amount"]
            support_oppose = expenditure["support_oppose"]

            if candidate_id not in totals:
                totals[candidate_id] = {
                    "candidate_id": candidate_id,
                    "support": Decimal("0"),
                    "oppose": Decimal("0"),
                }

            if support_oppose == "S":
                totals[candidate_id]["support"] += amount

            elif support_oppose == "O":
                totals[candidate_id]["oppose"] += amount

        return totals