import os
import time
import httpx
from dotenv import load_dotenv
from app.schemas.candidate import CandidateResponse
from app.schemas.finance import CandidateFinanceResponse
from decimal import Decimal
from app.schemas.independent_expenditure import IndependentExpenditureSummary

load_dotenv()

BASE_URL = "https://api.open.fec.gov/v1"
FEC_API_KEY = os.getenv("FEC_API_KEY")


class FECClient:
    def __init__(self):
        if not FEC_API_KEY:
            raise RuntimeError("FEC_API_KEY is not configured")

        self.base_url = BASE_URL
        self.api_key = FEC_API_KEY

    def _get(
    self,
    endpoint: str,
    params: dict | None = None,
) -> dict:

        params = params.copy() if params else {}
        params["api_key"] = self.api_key

        max_retries = 5

        for attempt in range(max_retries):

            response = httpx.get(
                f"{self.base_url}{endpoint}",
                params=params,
                timeout=30.0,
            )

            if response.status_code == 429:
                wait_time = 2 ** attempt

                print(
                    f"FEC rate limit hit. "
                    f"Waiting {wait_time} seconds..."
                )

                time.sleep(wait_time)
                continue

            response.raise_for_status()
            return response.json()

        raise RuntimeError(
            "FEC API rate limit exceeded after retries"
        )

    def _get_all_pages(
    self,
    endpoint: str,
    params: dict | None = None,) -> list[dict]:
        
        params = params.copy() if params else {}
        page = 1
        results = []

        while True:
            params["page"] = page
            params["per_page"] = 100

            data = self._get(
                endpoint,
                params=params,
            )

            page_results = data.get("results", [])

            results.extend(page_results)

            pagination = data.get("pagination", {})
            pages = pagination.get("pages", 1)

            if page >= pages:
                break

            page += 1

        return results

    def get_candidates(self,state: str,office: str,cycle: int,) -> list[CandidateResponse]:

        data = self._get(
            "/candidates/",
            params={
                "state": state.upper(),
                "office": office.upper(),
                "election_year": cycle,
                "per_page": 100,
            },
        )

        return [
            CandidateResponse(
                candidate_id=candidate["candidate_id"],
                name=candidate["name"],
                party=candidate.get("party"),
                office=candidate["office"],
                state=candidate.get("state"),
                district=candidate.get("district"),
            )
            for candidate in data["results"]
        ]

    def get_candidate_finances(self,candidate_id: str, cycle: int,) -> CandidateFinanceResponse | None:

        params = {
            "api_key": self.api_key,
            "candidate_id": candidate_id,
            "cycle": cycle,
            "per_page": 100,
        }

        data = self._get(
            f"/candidate/{candidate_id}/totals/",
            params={
                "cycle": cycle,
                "per_page": 100,
            },
        )

        results = data["results"]

        if not results:
            return None

        finance = results[0]

        return CandidateFinanceResponse(
            candidate_id=candidate_id,
            cycle=cycle,
            receipts=finance.get("receipts", 0) or 0,
            disbursements=finance.get("disbursements", 0) or 0,
            cash_on_hand=finance.get("last_cash_on_hand_end_period", 0) or 0,
            individual_contributions=finance.get(
                "individual_contributions",
                0,
            ) or 0,
            contributions_from_other_committees=finance.get(
                "other_political_committee_contributions",
                0,
            ) or 0,
        )

    def get_independent_expenditures(self,candidate_id: str,cycle: int,) -> IndependentExpenditureSummary:

        expenditures = self._get_all_pages(
            "/schedules/schedule_e/by_candidate/",
            params={
                "candidate_id": candidate_id,
                "cycle": cycle,
            },
        )

        support = Decimal("0")
        oppose = Decimal("0")

        for expenditure in expenditures:
            amount = Decimal(
                str(expenditure.get("total", 0) or 0)
            )

            support_oppose = expenditure.get(
                "support_oppose_indicator"
            )

            if support_oppose == "S":
                support += amount

            elif support_oppose == "O":
                oppose += amount

        return IndependentExpenditureSummary(
            candidate_id=candidate_id,
            cycle=cycle,
            support=support,
            oppose=oppose,
            total=support + oppose,
        )