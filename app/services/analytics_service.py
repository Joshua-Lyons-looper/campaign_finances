from sqlalchemy import select, union
from sqlalchemy.orm import Session
from app.models.candidate import Candidate
from app.models.candidate_finance import CandidateFinance
from app.models.election_result import ElectionResult
from app.models.outside_spending import OutsideSpending
from decimal import Decimal
class AnalyticsService:

    def __init__(self, db: Session):
        self.db = db

    def get_state_party_totals(self,cycle: int,state: str,office: str,) -> dict:

        query = select(ElectionResult).where(
            ElectionResult.cycle == cycle,
            ElectionResult.office == office,
        )

        if state.upper() != "US":
            query = query.where(
                ElectionResult.state == state.upper()
            )

        results = self.db.scalars(query).all()

        party_votes = {}
        total_votes = 0
        usable_rows = 0

        for result in results:
            if result.general_votes is None:
                continue

            raw_votes = result.general_votes

            if isinstance(raw_votes, str):
                raw_votes = raw_votes.strip()

                if raw_votes in {"Unopposed", "#", ""}:
                    continue

                raw_votes = raw_votes.replace(",", "")

            try:
                votes = int(raw_votes)

            except (ValueError, TypeError):
                print(
                    "UNHANDLED VOTE VALUE:",
                    result.state,
                    result.district,
                    result.candidate_name,
                    repr(result.general_votes),
                )
                continue

            if votes < 0:
                continue

            usable_rows += 1
            total_votes += votes

            party = result.party or "OTHER"

            if party not in party_votes:
                party_votes[party] = 0

            party_votes[party] += votes

        parties = {}

        for party, votes in party_votes.items():

            vote_share = (
                votes / total_votes
                if total_votes
                else None
            )

            parties[party] = {
                "votes": votes,
                "vote_share": vote_share,
            }

        return {
            "cycle": cycle,
            "state": state.upper(),
            "office": office,
            "available": usable_rows > 0,
            "vote_shares_available": total_votes > 0,
            "total_votes": total_votes,
            "parties": parties,
        }

    def compare_state_cycles(self,state: str,from_cycle: int,to_cycle: int,office: str,) -> dict:
        # Senate comparisons aggregate statewide parties, not necessarily the same seat.

        from_data = self.get_state_party_totals(
            cycle=from_cycle,
            state=state,
            office=office,
        )

        to_data = self.get_state_party_totals(
            cycle=to_cycle,
            state=state,
            office=office,
        )

        missing = {
            "from_cycle": not from_data["available"],
            "to_cycle": not to_data["available"],
        }
        available = all(
            data["vote_shares_available"] for data in (from_data, to_data)
        )
        comparison = {
            "state": state.upper(),
            "office": office,
            "from_cycle": from_cycle,
            "to_cycle": to_cycle,
            "available": available,
            "missing": missing,
            "from_total_votes": from_data["total_votes"] if from_data["available"] else None,
            "to_total_votes": to_data["total_votes"] if to_data["available"] else None,
            "parties": {},
        }
        if not available:
            return comparison

        all_parties = (
            set(from_data["parties"])
            | set(to_data["parties"])
        )

        parties = {}

        for party in all_parties:

            from_party = from_data["parties"].get(party)
            to_party = to_data["parties"].get(party)

            from_share = (
                from_party["vote_share"]
                if from_party
                else 0
            )

            to_share = (
                to_party["vote_share"]
                if to_party
                else 0
            )

            parties[party] = {
                "from_vote_share": from_share,
                "to_vote_share": to_share,
                "change_percentage_points": (
                    to_share - from_share
                ) * 100,
            }

        comparison["parties"] = parties
        return comparison

    def get_state_party_finances(self,cycle: int,state: str,office: str,) -> dict:
        
        
        query = (
            select(ElectionResult, Candidate, CandidateFinance)
            .outerjoin(
                Candidate,
                Candidate.fec_candidate_id == ElectionResult.fec_candidate_id,
            )
            .outerjoin(
                CandidateFinance,
                (CandidateFinance.candidate_id == Candidate.id)
                & (CandidateFinance.cycle == cycle),
            )
            .where(
                ElectionResult.cycle == cycle,
                ElectionResult.office == office,
            )
        )

        if state.upper() != "US":
            query = query.where(
                ElectionResult.state == state.upper()
            )

        rows = self.db.execute(query).all()

        parties = {}

        for result, candidate, finance in rows:

            if finance is None or not self._usable_amounts(finance.receipts, finance.disbursements):
                continue

            party = result.party or "OTHER"

            if party not in parties:
                parties[party] = {
                    "receipts": 0,
                    "spent": 0,
                }

            parties[party]["receipts"] += finance.receipts
            parties[party]["spent"] += finance.disbursements

        return {
            "cycle": cycle,
            "state": state.upper(),
            "office": office,
            "available": bool(parties),
            "parties": parties,
        }


    def compare_state_finances(self,state: str,from_cycle: int,to_cycle: int,office: str,) -> dict:
        election_comparison = self.compare_state_cycles(
            state=state,
            office=office,
            from_cycle=from_cycle,
            to_cycle=to_cycle,
        )

        from_finances = self.get_state_party_finances(
            cycle=from_cycle,
            state=state,
            office=office,
        )

        to_finances = self.get_state_party_finances(
            cycle=to_cycle,
            state=state,
            office=office,
        )
        from_outside = self.get_state_party_outside_spending(
            cycle=from_cycle,
            state=state,
            office=office,
        )

        to_outside = self.get_state_party_outside_spending(
            cycle=to_cycle,
            state=state,
            office=office,
        )


        parties = {}

        for party, election_data in election_comparison["parties"].items():

            from_finance = from_finances["parties"].get(party)
            to_finance = to_finances["parties"].get(party)

            from_spent = (
                from_finance["spent"]
                if from_finance
                else None
            )

            to_spent = (
                to_finance["spent"]
                if to_finance
                else None
            )


            spending_change = None
            spending_percent_change = None

            if from_spent is not None and to_spent is not None:

                spending_change = to_spent - from_spent

                if from_spent != 0:
                    spending_percent_change = (
                        spending_change / from_spent
                    ) * 100

            spending_per_percentage_point_change = None
            spending_change_per_percentage_point_change = None

            vote_share_change = Decimal(
                str(election_data["change_percentage_points"])
            )

            if vote_share_change != 0:

                if to_spent is not None:
                    spending_per_percentage_point_change = (
                        to_spent / vote_share_change
                    )

                if spending_change is not None:
                    spending_change_per_percentage_point_change = (
                        spending_change / vote_share_change
                    )

            from_outside_party = from_outside["parties"].get(party)
            to_outside_party = to_outside["parties"].get(party)

            from_outside_total = (
                from_outside_party["total"]
                if from_outside_party
                else None
            )

            to_outside_total = (
                to_outside_party["total"]
                if to_outside_party
                else None
            )

            outside_change = None
            outside_percent_change = None

            if (
                from_outside_total is not None
                and to_outside_total is not None
            ):
                outside_change = (
                    to_outside_total
                    - from_outside_total
                )

                if from_outside_total != 0:
                    outside_percent_change = (
                        outside_change
                        / from_outside_total
                    ) * 100

            parties[party] = {
                "from_vote_share":
                    election_data["from_vote_share"],

                "to_vote_share":
                    election_data["to_vote_share"],

                "vote_share_change_percentage_points":
                    election_data["change_percentage_points"],

                "candidate_spending": {
                    "from": from_spent,
                    "to": to_spent,
                    "change": spending_change,
                    "percent_change": spending_percent_change,
                    "per_percentage_point_change":
                        spending_per_percentage_point_change,   
                    "spending_change_per_percentage_point_change": spending_change_per_percentage_point_change,
                },
                "outside_spending": {
                    "from": {
                        "support": (
                            from_outside_party["support"]
                            if from_outside_party
                            else None
                        ),
                        "oppose": (
                            from_outside_party["oppose"]
                            if from_outside_party
                            else None
                        ),
                        "total": from_outside_total,
                    },

                    "to": {
                        "support": (
                            to_outside_party["support"]
                            if to_outside_party
                            else None
                        ),
                        "oppose": (
                            to_outside_party["oppose"]
                            if to_outside_party
                            else None
                        ),
                        "total": to_outside_total,
                    },

                    "change": outside_change,
                    "percent_change": outside_percent_change,
                },
            }

        return {
            "state": state.upper(),
            "office": office,
            "from_cycle": from_cycle,
            "to_cycle": to_cycle,
            "available": election_comparison["available"],
            "missing": election_comparison["missing"],
            "data_coverage": {
                str(from_cycle): {
                    "election_results": not election_comparison["missing"]["from_cycle"],
                    "candidate_finances": from_finances["available"],
                    "independent_expenditures": from_outside["available"],
                },
                str(to_cycle): {
                    "election_results": not election_comparison["missing"]["to_cycle"],
                    "candidate_finances": to_finances["available"],
                    "independent_expenditures": to_outside["available"],
                },
            },
            "parties": parties,
        }

    def get_state_party_outside_spending(self,cycle: int,state: str,office: str,) -> dict:
        query = (
            select(ElectionResult, Candidate, OutsideSpending)
            .outerjoin(
                Candidate,
                Candidate.fec_candidate_id == ElectionResult.fec_candidate_id,
            )
            .outerjoin(
                OutsideSpending,
                (OutsideSpending.candidate_id == Candidate.id)
                & (OutsideSpending.cycle == cycle),
            )
            .where(
                ElectionResult.cycle == cycle,
                ElectionResult.office == office,
            )
        )

        if state.upper() != "US":
            query = query.where(
                ElectionResult.state == state.upper()
            )

        rows = self.db.execute(query).all()

        parties = {}

        for result, candidate, outside_spending in rows:

            if outside_spending is None or not self._usable_amounts(outside_spending.support, outside_spending.oppose):
                continue

            party = result.party or "OTHER"

            if party not in parties:
                parties[party] = {
                    "support": 0,
                    "oppose": 0,
                }

            parties[party]["support"] += outside_spending.support
            parties[party]["oppose"] += outside_spending.oppose

        for party in parties:
            parties[party]["total"] = (
                parties[party]["support"]
                + parties[party]["oppose"]
            )

        return {
            "cycle": cycle,
            "state": state.upper(),
            "office": office,
            "available": bool(parties),
            "parties": parties,
        }

    @staticmethod
    def _usable_amounts(*amounts) -> bool:
        # Explicit numeric zero is usable; absent/non-finite amounts are not.
        try:
            return all(value is not None and Decimal(str(value)).is_finite() for value in amounts)
        except (ValueError, TypeError, ArithmeticError):
            return False

    def get_data_coverage(self, state: str = "US", office: str | None = None) -> dict:
        # Include financial-only cycles, even when election results are missing.
        scopes = union(
            select(ElectionResult.cycle, ElectionResult.office),
            select(CandidateFinance.cycle, Candidate.office).join(
                Candidate, Candidate.id == CandidateFinance.candidate_id),
            select(OutsideSpending.cycle, Candidate.office).join(
                Candidate, Candidate.id == OutsideSpending.candidate_id),
        )
        coverage = {}
        for cycle, office_code in sorted(self.db.execute(scopes).all()):
            if office_code not in {"H", "S"} or (office and office_code != office):
                continue
            coverage.setdefault(str(cycle), {})[office_code] = {
                "election_results": self.get_state_party_totals(cycle, state, office_code)["available"],
                "candidate_finances": self.get_state_party_finances(cycle, state, office_code)["available"],
                "independent_expenditures": self.get_state_party_outside_spending(cycle, state, office_code)["available"],
            }
        return {"state": state.upper(), "data_coverage": coverage}

    # Backward-compatible House entry points delegate to shared implementations.
    def get_state_house_party_totals(self, cycle: int, state: str) -> dict:
        return self.get_state_party_totals(cycle=cycle, state=state, office="H")

    def compare_state_house_cycles(self, state: str, from_cycle: int, to_cycle: int) -> dict:
        return self.compare_state_cycles(
            state=state, from_cycle=from_cycle, to_cycle=to_cycle, office="H",
        )

    def get_state_house_party_finances(self, cycle: int, state: str) -> dict:
        return self.get_state_party_finances(cycle=cycle, state=state, office="H")

    def get_state_house_party_outside_spending(self, cycle: int, state: str) -> dict:
        return self.get_state_party_outside_spending(cycle=cycle, state=state, office="H")

    def compare_state_house_finances(self, state: str, from_cycle: int, to_cycle: int) -> dict:
        return self.compare_state_finances(
            state=state, from_cycle=from_cycle, to_cycle=to_cycle, office="H",
        )
