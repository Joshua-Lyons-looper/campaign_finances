"""Read PAS2 without conflating direct contributions with outside spending."""
import csv
from decimal import Decimal
import zipfile
from app.services.fec_bulk_importer import FECBulkImporter

DIRECT_TYPES = {"24K", "24Z"}  # Cash and in-kind to registered committees.
PAC_TYPES = {"N", "Q", "V", "W"}


class PACBulkImporter(FECBulkImporter):
    def rows(self, cycle, prefix, member, width):
        with zipfile.ZipFile(self.data_directory / f"{prefix}{str(cycle)[-2:]}.zip") as archive:
            with archive.open(member) as file:
                for line, row in enumerate(csv.reader(
                    (r.decode("utf-8-sig") for r in file), delimiter="|"), 1):
                    if len(row) != width:
                        raise ValueError(f"{member}:{line}: expected {width} columns")
                    yield [value.strip() for value in row]

    def read_committees(self, cycle):
        for row in self.rows(cycle, "cm", "cm.txt", 15):
            yield dict(committee_id=row[0], committee_name=row[1] or None,
                       committee_type=row[9] or None)

    def read_contributions(self, cycle):
        for row in self.rows(cycle, "pas2", "itpas2.txt", 22):
            if row[5] not in DIRECT_TYPES:
                continue
            if not row[0] or not row[21]:
                raise ValueError("Contribution missing committee ID or SUB_ID")
            amount = Decimal(row[14]) if row[14] else None
            if amount is not None and (not amount.is_finite() or amount != amount.quantize(Decimal('.01'))):
                raise ValueError(f"Invalid amount for SUB_ID {row[21]}")
            yield dict(committee_id=row[0], fec_candidate_id=row[16] or None,
                       recipient_committee_id=row[15] or None, amount=amount,
                       sub_id=row[21], transaction_id=row[17] or None,
                       file_number=row[18] or None, amendment_indicator=row[1] or None,
                       transaction_type=row[5], memo_code=row[19] or None)
