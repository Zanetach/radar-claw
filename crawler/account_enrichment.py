from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class AccountIdentifier:
    platform: str
    account_name: str
    account_handle: str | None = None
    account_url: str | None = None


SEED_IDENTIFIERS = [
    AccountIdentifier("x", "Donald J. Trump", "realDonaldTrump", "https://x.com/realDonaldTrump"),
    AccountIdentifier("x", "Narendra Modi", "narendramodi", "https://x.com/narendramodi"),
    AccountIdentifier("x", "Emmanuel Macron", "EmmanuelMacron", "https://x.com/EmmanuelMacron"),
    AccountIdentifier("x", "Rishi Sunak", "RishiSunak", "https://x.com/RishiSunak"),
    AccountIdentifier("x", "Ursula von der Leyen", "vonderleyen", "https://x.com/vonderleyen"),
    AccountIdentifier("x", "Mike Pompeo", "mikepompeo", "https://x.com/mikepompeo"),
    AccountIdentifier("x", "Marco Rubio", "marcorubio", "https://x.com/marcorubio"),
    AccountIdentifier("x", "Olaf Scholz", "OlafScholz", "https://x.com/OlafScholz"),
    AccountIdentifier("x", "Ray Dalio", "RayDalio", "https://x.com/RayDalio"),
    AccountIdentifier("x", "Cathie Wood", "CathieDWood", "https://x.com/CathieDWood"),
    AccountIdentifier("x", "Howard Marks", "HowardMarksBook", "https://x.com/HowardMarksBook"),
    AccountIdentifier("x", "Jamie Dimon", "JamieDimon", "https://x.com/JamieDimon"),
    AccountIdentifier("x", "Stephen Schwarzman", "blackstone", "https://x.com/blackstone"),
    AccountIdentifier("x", "Jeremy Grantham", "Jeremy_Grantham", "https://x.com/Jeremy_Grantham"),
    AccountIdentifier("x", "Elon Musk", "elonmusk", "https://x.com/elonmusk"),
    AccountIdentifier("x", "Bill Gates", "BillGates", "https://x.com/BillGates"),
    AccountIdentifier("x", "Jeff Bezos", "JeffBezos", "https://x.com/JeffBezos"),
    AccountIdentifier("x", "Mark Zuckerberg", "finkd", "https://x.com/finkd"),
    AccountIdentifier("x", "Jensen Huang", "nvidia", "https://x.com/nvidia"),
    AccountIdentifier("x", "Tim Cook", "tim_cook", "https://x.com/tim_cook"),
    AccountIdentifier("x", "Lisa Su", "LisaSu", "https://x.com/LisaSu"),
    AccountIdentifier("x", "Satya Nadella", "satyanadella", "https://x.com/satyanadella"),
    AccountIdentifier("x", "Larry Ellison", "Oracle", "https://x.com/Oracle"),
    AccountIdentifier("x", "Masayoshi Son", "masason", "https://x.com/masason"),
    AccountIdentifier("x", "Reed Hastings", "reedhastings", "https://x.com/reedhastings"),
    AccountIdentifier("x", "Andy Jassy", "ajassy", "https://x.com/ajassy"),
    AccountIdentifier("x", "Alex Hormozi", "AlexHormozi", "https://x.com/AlexHormozi"),
    AccountIdentifier("x", "Gary Vaynerchuk", "garyvee", "https://x.com/garyvee"),
    AccountIdentifier("x", "Grant Cardone", "GrantCardone", "https://x.com/GrantCardone"),
    AccountIdentifier("x", "Tim Ferriss", "tferriss", "https://x.com/tferriss"),
    AccountIdentifier("x", "Tony Robbins", "TonyRobbins", "https://x.com/TonyRobbins"),
    AccountIdentifier("x", "Russell Brunson", "russellbrunson", "https://x.com/russellbrunson"),
    AccountIdentifier("x", "Patrick Bet-David", "patrickbetdavid", "https://x.com/patrickbetdavid"),
    AccountIdentifier("x", "Noah Kagan", "noahkagan", "https://x.com/noahkagan"),
    AccountIdentifier("x", "Robert Kiyosaki", "theRealKiyosaki", "https://x.com/theRealKiyosaki"),
    AccountIdentifier("x", "Graham Stephan", "GrahamStephan", "https://x.com/GrahamStephan"),
    AccountIdentifier("x", "Ben Felix", "benjaminwfelix", "https://x.com/benjaminwfelix"),
    AccountIdentifier("x", "Aswath Damodaran", "AswathDamodaran", "https://x.com/AswathDamodaran"),
    AccountIdentifier("x", "Simon Sinek", "simonsinek", "https://x.com/simonsinek"),
    AccountIdentifier("x", "Brené Brown", "BreneBrown", "https://x.com/BreneBrown"),
    AccountIdentifier("x", "Robin Sharma", "RobinSharma", "https://x.com/RobinSharma"),
    AccountIdentifier("x", "Arianna Huffington", "ariannahuff", "https://x.com/ariannahuff"),
    AccountIdentifier("x", "Daniel Goleman", "DanielGolemanEI", "https://x.com/DanielGolemanEI"),
    AccountIdentifier("youtube", "Alex Hormozi", "@AlexHormozi", "https://www.youtube.com/@AlexHormozi"),
    AccountIdentifier("youtube", "Gary Vaynerchuk", "@garyvee", "https://www.youtube.com/@garyvee"),
    AccountIdentifier("youtube", "Grant Cardone", "@GrantCardone", "https://www.youtube.com/@GrantCardone"),
    AccountIdentifier("youtube", "Tim Ferriss", "@timferriss", "https://www.youtube.com/@timferriss"),
    AccountIdentifier("youtube", "Tony Robbins", "@TonyRobbinsLive", "https://www.youtube.com/@TonyRobbinsLive"),
    AccountIdentifier("youtube", "Russell Brunson", "@RussellBrunson", "https://www.youtube.com/@RussellBrunson"),
    AccountIdentifier("youtube", "Patrick Bet-David", "@VALUETAINMENT", "https://www.youtube.com/@VALUETAINMENT"),
    AccountIdentifier("youtube", "Noah Kagan", "@noahkagan", "https://www.youtube.com/@noahkagan"),
    AccountIdentifier("youtube", "Robert Kiyosaki", "@TheRichDadChannel", "https://www.youtube.com/@TheRichDadChannel"),
    AccountIdentifier("youtube", "Graham Stephan", "@GrahamStephan", "https://www.youtube.com/@GrahamStephan"),
    AccountIdentifier("youtube", "Ben Felix", "@BenFelixCSI", "https://www.youtube.com/@BenFelixCSI"),
    AccountIdentifier("youtube", "Phil Town", "@Rule1Investing", "https://www.youtube.com/@Rule1Investing"),
    AccountIdentifier("youtube", "The Money Guy Show", "@MoneyGuyShow", "https://www.youtube.com/@MoneyGuyShow"),
    AccountIdentifier("youtube", "Aswath Damodaran", "@AswathDamodaranonValuation", "https://www.youtube.com/@AswathDamodaranonValuation"),
]


def enrich_accounts(conn: sqlite3.Connection, *, overwrite: bool = False) -> dict[str, int]:
    updated = 0
    skipped = 0
    missing = 0
    for item in SEED_IDENTIFIERS:
        row = conn.execute(
            """
            SELECT id, account_handle, account_url
            FROM source_accounts
            WHERE platform = ? AND account_name = ?
            """,
            (item.platform, item.account_name),
        ).fetchone()
        if row is None:
            missing += 1
            continue
        if not overwrite and (row["account_handle"] or row["account_url"]):
            skipped += 1
            continue
        conn.execute(
            """
            UPDATE source_accounts
            SET account_handle = COALESCE(?, account_handle),
                account_url = COALESCE(?, account_url),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (item.account_handle, item.account_url, row["id"]),
        )
        updated += 1
    conn.commit()
    return {"updated": updated, "skipped": skipped, "missing": missing, "seeds": len(SEED_IDENTIFIERS)}
