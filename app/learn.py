from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    key: str
    term: str
    explanation: str
    example: str


GLOSSARY_ENTRIES: list[GlossaryEntry] = [
    GlossaryEntry(
        key="voucher",
        term="Bilag (voucher)",
        explanation="Et bilag er en bokforingshendelse med en eller flere posteringer som henger sammen.",
        example="Faktura fra kunde og innbetaling på konto blir bokført i samme bilag.",
    ),
    GlossaryEntry(
        key="posting",
        term="Postering",
        explanation="En linje i bilaget som bokfører et beløp på én konto i debet eller kredit.",
        example="1920 Bank i debet 1 000 og 3100 Salgsinntekt i kredit 1 000.",
    ),
    GlossaryEntry(
        key="debit_credit",
        term="Debet / Kredit",
        explanation="To sider i dobbel bokføring. Summen av debet må alltid være lik summen av kredit i bilaget.",
        example="Kjøp av PC: kostnad i debet, bank i kredit.",
    ),
    GlossaryEntry(
        key="account_chart",
        term="Konto / Kontoplan",
        explanation="Konto er kategorien du bokfører på. Kontoplan er hele listen over kontoer.",
        example="1920 Bank, 3000 Salgsinntekt, 5000 Driftskostnad.",
    ),
    GlossaryEntry(
        key="term",
        term="Termin",
        explanation="MVA-perioden i året. Systemet bruker 6 terminer (to måneder per termin).",
        example="Termin 1 dekker januar og februar.",
    ),
    GlossaryEntry(
        key="lock_term",
        term="Lås termin",
        explanation="Når en termin låses, kan du ikke bokføre vanlige nye endringer i perioden.",
        example="Etter innsending av MVA for termin 2 låser du termin 2.",
    ),
    GlossaryEntry(
        key="reversal_correction",
        term="Reversering / Korrigering",
        explanation="Feil rettes ved å reversere gammelt bilag og deretter føre et nytt korrekt bilag.",
        example="Du oppdager feil konto: opprett korreksjon fra bilagsdetaljen.",
    ),
    GlossaryEntry(
        key="input_vat",
        term="Inngående MVA",
        explanation="MVA du betaler på kjøp i virksomheten. Denne kan normalt trekkes fra i MVA-oppgaven.",
        example="PC-kjøp med 25 % MVA gir inngående MVA.",
    ),
    GlossaryEntry(
        key="output_vat",
        term="Utgående MVA",
        explanation="MVA du beregner på salg som er avgiftspliktig.",
        example="Salg med mvaKode 3 gir utgående MVA.",
    ),
    GlossaryEntry(
        key="vat_code",
        term="MVA-kode",
        explanation="Kode som forteller hvilken MVA-behandling linjen skal ha i spesifikasjonen.",
        example="mvaKode 3 for vanlig utgående MVA, 81 for inngående MVA.",
    ),
    GlossaryEntry(
        key="vat_base",
        term="Grunnlag",
        explanation="Beløpet MVA beregnes av, før selve MVA-beløpet.",
        example="Grunnlag 1 000 med sats 25 % gir MVA 250.",
    ),
    GlossaryEntry(
        key="vat_rate",
        term="Sats",
        explanation="Prosentsatsen som brukes for MVA-beregningen.",
        example="Vanlig sats er 25 %.",
    ),
    GlossaryEntry(
        key="vat_amount",
        term="MVA-beløp",
        explanation="Selve avgiftsbeløpet på linjen.",
        example="Ved grunnlag 400 og sats 25 % blir MVA-beløp 100.",
    ),
    GlossaryEntry(
        key="journal",
        term="Journal (bokføringsspesifikasjon)",
        explanation="Liste over alle posteringer i valgt periode med bilagsreferanser.",
        example="Brukes ved kontroll og avstemming.",
    ),
    GlossaryEntry(
        key="account_spec",
        term="Kontospesifikasjon",
        explanation="Alle posteringer på én konto, med løpende saldo.",
        example="Vis konto 1920 for å se alle bankbevegelser.",
    ),
    GlossaryEntry(
        key="vat_spec",
        term="MVA-spesifikasjon",
        explanation="Oppstilling av grunnlag og MVA per mvaKode for valgt termin.",
        example="Brukes når du kontrollerer tall før MVA-melding.",
    ),
]


TOOLTIPS: dict[str, str] = {
    "voucher_type": "Type bilag, for eksempel manuelt, reversering eller korrigering.",
    "posting_date": "Bokføringsdatoen som avgjør hvilken termin posteringen havner i.",
    "document_date": "Dokumentdato fra kvittering/faktura.",
    "debet_kredit": "Debet og kredit må alltid balansere i et bilag.",
    "account_chart": "Velg konto fra kontoplanen som passer hendelsen.",
    "vat_code": "MVA-kode styrer hvordan linjen vises i MVA-spesifikasjonen.",
    "vat_base": "Grunnlaget er beløpet MVA beregnes av.",
    "vat_rate": "Sats i prosent, for eksempel 25.",
    "vat_amount": "MVA-beløpet i kroner for linjen.",
    "journal": "Journal viser alle posteringer i valgt datoperiode.",
    "account_spec": "Kontospesifikasjon viser posteringer og løpende saldo per konto.",
    "vat_spec": "MVA-spesifikasjon summerer grunnlag og MVA per kode.",
    "term": "Termin er MVA-perioden (to måneder).",
    "lock_term": "Låsing gjør perioden skrivebeskyttet for vanlige posteringer.",
    "correction": "Korrigering lager reversering + nytt korrekt bilag.",
    "input_vat": "Inngående MVA er MVA på kjøp.",
    "output_vat": "Utgående MVA er MVA på salg.",
}


GETTING_STARTED_STEPS: list[dict[str, str]] = [
    {
        "id": "a",
        "title": "Bootstrap admin og logg inn",
        "body": "Gå til /bootstrap-admin, opprett første adminbruker og logg inn med samme bruker.",
    },
    {
        "id": "b",
        "title": "Fyll ut innstillinger",
        "body": "Åpne Innstillinger og legg inn firmanavn, org.nr., standardvalg og riktig år/termin.",
    },
    {
        "id": "c",
        "title": "Før inntekt fra eksempeloppdrag",
        "body": "Opprett nytt bilag: debet 1920 Bank, kredit 3100/3000 inntekt. Legg inn mvaKode ved behov.",
    },
    {
        "id": "d",
        "title": "Før kostnad (for eksempel PC-kjøp)",
        "body": "Eksempel: debet kostnadskonto + ev. inngående MVA, kredit 1920 Bank.",
    },
    {
        "id": "e",
        "title": "Legg ved bilag",
        "body": "Last opp PDF/JPG/PNG i bilaget, så dokumentasjonen følger bokføringen.",
    },
    {
        "id": "f",
        "title": "Kjør rapporter",
        "body": "Bruk Rapporter for årsoversikt, journal, kontospesifikasjon og MVA-spesifikasjon.",
    },
    {
        "id": "g",
        "title": "Lås termin når du er ferdig",
        "body": "I Innstillinger låser du termin etter kontroll og innsending, så perioden ikke endres ved et uhell.",
    },
    {
        "id": "h",
        "title": "Rett feil med korreksjon",
        "body": "Åpne bilaget og velg korreksjon. Systemet lager reversering og nytt korrigert bilag.",
    },
]
