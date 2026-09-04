#!/usr/bin/env python3
"""Baixa voos da API pública SIROS/ANAC e atualiza os artefatos locais."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_URL = "https://sas.anac.gov.br/sas/siros_api/api/voosPeriodo"


def environment_value(name: str, fallback: str) -> str:
    value = os.getenv(name, "").strip()
    return value or fallback


def parse_args() -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=environment_value("SIROS_API_URL", DEFAULT_API_URL))
    parser.add_argument("--start-date", default=environment_value("SIROS_START_DATE", today.isoformat()))
    parser.add_argument("--end-date", default=environment_value("SIROS_END_DATE", (today + timedelta(days=30)).isoformat()))
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "flights.json")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "flights.db")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--skip-supabase", action="store_true", help="não envia os registros ao Supabase")
    return parser.parse_args()


def fetch_payload(url: str, start_date: str, end_date: str, timeout: int) -> Any:
    if not url.startswith(("http://", "https://")):
        raise ValueError("SIROS_API_URL deve ser uma URL HTTP ou HTTPS válida")
    query = urlencode({"dataReferenciaInicio": start_date, "dataReferenciaFinal": end_date})
    request = Request(url + ("&" if "?" in url else "?") + query, headers={"Accept": "application/json", "User-Agent": "siros-flight-dashboard/1.0"})
    token = os.getenv("SIROS_API_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = next((payload[key] for key in ("data", "dados", "results", "resultados", "items", "voos") if isinstance(payload.get(key), list)), [])
    else:
        records = []
    return [record for record in records if isinstance(record, dict)]


def value(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        item = record.get(key)
        if item is not None and item != "":
            return str(item)
    return ""


def normalize(record: dict[str, Any]) -> dict[str, str]:
    return {
        "flight_number": value(record, "numeroVoo", "numero_voo", "flightNumber", "voo", "numVoo"),
        "operator": value(record, "empresa", "empresaNome", "operador", "operator", "companhia"),
        "origin": value(record, "aeroportoOrigem", "origem", "origin", "origemIata"),
        "destination": value(record, "aeroportoDestino", "destino", "destination", "destinoIata"),
        "departure": value(record, "dataHoraPartida", "partida", "departure", "dataPartida"),
        "arrival": value(record, "dataHoraChegada", "chegada", "arrival", "dataChegada"),
        "status": value(record, "situacao", "status", "situacaoVoo") or "Programado",
    }


def write_outputs(records: list[dict[str, str]], output: Path, database: Path, start_date: str, end_date: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    document = {"updated_at": date.today().isoformat(), "period": {"start": start_date, "end": end_date}, "count": len(records), "flights": records}
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS flights (
                id INTEGER PRIMARY KEY,
                flight_number TEXT NOT NULL,
                operator TEXT NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                departure TEXT NOT NULL,
                arrival TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(flight_number, departure, origin, destination)
            );
        """)
        connection.execute("DELETE FROM flights")
        connection.executemany(
            "INSERT OR REPLACE INTO flights (flight_number, operator, origin, destination, departure, arrival, status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(item["flight_number"], item["operator"], item["origin"], item["destination"], item["departure"], item["arrival"], item["status"], document["updated_at"]) for item in records],
        )


def write_supabase(records: list[dict[str, str]], timeout: int) -> None:
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_role_key:
        raise RuntimeError("defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY")

    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/flights?on_conflict=flight_number,departure,origin,destination"
    request = Request(
        endpoint,
        data=json.dumps(records).encode("utf-8"),
        method="POST",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status >= 300:
            raise RuntimeError(f"Supabase respondeu HTTP {response.status}")


def main() -> int:
    args = parse_args()
    try:
        payload = fetch_payload(args.api_url, args.start_date, args.end_date, args.timeout)
        records = [normalize(record) for record in extract_records(payload)]
        write_outputs(records, args.output, args.database, args.start_date, args.end_date)
        if not args.skip_supabase:
            write_supabase(records, args.timeout)
        destino = "localmente e no Supabase" if not args.skip_supabase else "localmente"
        print(f"{len(records)} voos gravados {destino}")
        return 0
    except Exception as error:  # noqa: BLE001 - transforma falhas de rede em erro de CLI claro
        print(f"Erro ao consultar a SIROS: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
