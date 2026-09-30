import zipfile
import csv
from pathlib import Path

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
                        "receipts": row[5],
                        "disbursements": row[7],
                        "cash_on_hand": row[10],
                        "individual_contributions": row[17],
                        "other_committee_contributions": row[25],
                    }
        return finances