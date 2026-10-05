import argparse
import csv
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.intercom.io"
API_VERSION = "2.16"
PAGE_SIZE = 150
HTTP_SESSION = requests.Session()
MERGE_PRIMARY_PART = "merged_primary_conversation"
MERGE_SECONDARY_PART = "merged_secondary_conversation"
MERGE_EVENT_TOLERANCE_SECONDS = 5
PRIMARY_UPDATE_GRACE_SECONDS = 7 * 24 * 60 * 60
REPORT_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def api_get(token, path, params=None):
    response = HTTP_SESSION.get(
        f"{API_URL}{path}",
        params=params,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Intercom-Version": API_VERSION,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def api_search(token, payload):
    response = HTTP_SESSION.post(
        f"{API_URL}/conversations/search",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Intercom-Version": API_VERSION,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def list_conversations(token, since_timestamp=None, until_timestamp=None):
    conversations = []
    starting_after = None
    while True:
        filters = []
        if since_timestamp is not None:
            filters.append({
                "field": "updated_at",
                "operator": ">",
                "value": str(since_timestamp),
            })
        if until_timestamp is not None:
            filters.append({
                "field": "updated_at",
                "operator": "<",
                "value": str(until_timestamp),
            })

        if filters:
            payload = {
                "query": filters[0] if len(filters) == 1 else {
                    "operator": "AND",
                    "value": filters,
                },
                "pagination": {"per_page": PAGE_SIZE},
            }
            if starting_after:
                payload["pagination"]["starting_after"] = starting_after
            result = api_search(token, payload)
        else:
            params = {"per_page": PAGE_SIZE}
            if starting_after:
                params["starting_after"] = starting_after
            result = api_get(token, "/conversations", params=params)

        conversations.extend(result.get("conversations", []))
        next_page = (result.get("pages") or {}).get("next") or {}
        starting_after = next_page.get("starting_after")
        if not starting_after:
            return conversations


def conversation_parts(conversation):
    return (
        (conversation.get("conversation_parts") or {}).get("conversation_parts") or []
    )


def merge_event_times(conversation, event_type):
    return [
        part["created_at"]
        for part in conversation_parts(conversation)
        if part.get("part_type") == event_type and part.get("created_at") is not None
    ]


def timestamp_to_iso(timestamp):
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def conversation_contact_ids(conversation):
    contacts = (conversation.get("contacts") or {}).get("contacts") or []
    return {
        str(contact["id"])
        for contact in contacts
        if contact.get("id") is not None
    }


def is_merged_secondary(summary):
    value = (summary.get("custom_attributes") or {}).get("Merged")
    return value is True or (isinstance(value, str) and value.casefold() == "true")


def build_report(token, since_timestamp=None, until_timestamp=None):
    search_since_timestamp = (
        max(0, since_timestamp - PRIMARY_UPDATE_GRACE_SECONDS)
        if since_timestamp is not None
        else None
    )
    search_until_timestamp = (
        until_timestamp + PRIMARY_UPDATE_GRACE_SECONDS
        if until_timestamp is not None
        else None
    )
    summaries = list_conversations(
        token, search_since_timestamp, search_until_timestamp
    )
    summaries_by_id = {
        str(summary["id"]): summary
        for summary in summaries
        if summary.get("id") is not None
    }
    details = {}
    details_by_contact = {}

    def get_details(summary):
        conversation_id = str(summary.get("id", ""))
        if not conversation_id:
            return None
        if conversation_id not in details:
            detail = api_get(
                token, f"/conversations/{conversation_id}"
            )
            details[conversation_id] = detail
            for contact_id in conversation_contact_ids(detail):
                details_by_contact.setdefault(contact_id, set()).add(conversation_id)
        return details[conversation_id]

    def event_is_in_range(event_time):
        return (
            (since_timestamp is None or event_time >= since_timestamp)
            and (until_timestamp is None or event_time <= until_timestamp)
        )

    rows = {}
    secondary_summaries = [
        summary
        for summary in summaries
        if summary.get("state") == "closed" and is_merged_secondary(summary)
    ]

    for secondary_summary in secondary_summaries:
        secondary = get_details(secondary_summary)
        if not secondary:
            continue
        secondary_id = str(secondary.get("id", ""))
        contact_ids = conversation_contact_ids(secondary)

        for secondary_event_time in merge_event_times(secondary, MERGE_SECONDARY_PART):
            if not event_is_in_range(secondary_event_time):
                continue

            candidate_ids = {
                str(candidate_id)
                for contact_id in contact_ids
                for candidate_id in details_by_contact.get(contact_id, set())
                if candidate_id != secondary_id
            }
            candidate_ids.update(
                candidate_id
                for contact_id in contact_ids
                for candidate_id, candidate in summaries_by_id.items()
                if candidate_id != secondary_id
                and candidate_id not in details
                and contact_id in conversation_contact_ids(candidate)
                and candidate.get("updated_at", 0)
                >= secondary_event_time - MERGE_EVENT_TOLERANCE_SECONDS
                and candidate.get("updated_at", 0)
                <= secondary_event_time + PRIMARY_UPDATE_GRACE_SECONDS
            )
            candidate_primary_ids = set()
            for primary_id in candidate_ids:
                primary_summary = summaries_by_id.get(primary_id)
                if primary_summary is None:
                    continue
                primary = get_details(primary_summary)
                if not primary:
                    continue
                if any(
                    event_is_in_range(primary_event_time)
                    and abs(primary_event_time - secondary_event_time)
                    <= MERGE_EVENT_TOLERANCE_SECONDS
                    for primary_event_time in merge_event_times(
                        primary, MERGE_PRIMARY_PART
                    )
                ):
                    candidate_primary_ids.add(primary_id)

            if len(candidate_primary_ids) != 1:
                continue

            primary_id = candidate_primary_ids.pop()
            primary = details[primary_id]
            secondary_reason = (secondary.get("custom_attributes") or {}).get(
                "Motivo de Contato"
            )
            primary_reason = (primary.get("custom_attributes") or {}).get(
                "Motivo de Contato"
            )
            rows[(secondary_id, primary_id)] = {
                "id_secundaria_mesclada": secondary_id,
                "id_principal": primary_id,
                "motivo_contato_secundaria": (
                    str(secondary_reason)
                    if secondary_reason not in (None, "")
                    else ""
                ),
                "motivo_contato_principal": (
                    str(primary_reason) if primary_reason not in (None, "") else ""
                ),
                "status_secundaria": secondary.get("state", ""),
                "status_principal": primary.get("state", ""),
                "criada_secundaria_em_utc": timestamp_to_iso(secondary.get("created_at")),
                "mesclada_em_utc": timestamp_to_iso(secondary_event_time),
            }

    return list(rows.values())


def parse_since(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use a data no formato AAAA-MM-DD.") from error
    return int(parsed.timestamp())


def day_bounds(value):
    selected_day = datetime.strptime(value, "%Y-%m-%d").date()
    start = datetime.combine(selected_day, time.min, REPORT_TIMEZONE)
    next_day = datetime.combine(selected_day + timedelta(days=1), time.min, REPORT_TIMEZONE)
    return int(start.timestamp()), int(next_day.timestamp()) - 1


def main():
    parser = argparse.ArgumentParser(
        description="Gera CSV com conversas secundárias mescladas e suas conversas principais."
    )
    parser.add_argument(
        "--since",
        type=parse_since,
        help="Considera conversas atualizadas a partir desta data (AAAA-MM-DD).",
    )
    parser.add_argument(
        "--output",
        default="conversas_mescladas.csv",
        help="Caminho do CSV de saída (padrão: conversas_mescladas.csv).",
    )
    args = parser.parse_args()

    token = os.environ.get("INTERCOM_TOKEN")
    if not token:
        print("Defina a variável de ambiente INTERCOM_TOKEN.", file=sys.stderr)
        return 1

    try:
        rows = build_report(token, args.since)
        fields = [
            "id_secundaria_mesclada",
            "id_principal",
            "motivo_contato_secundaria",
            "motivo_contato_principal",
            "status_secundaria",
            "status_principal",
            "criada_secundaria_em_utc",
            "mesclada_em_utc",
        ]
        with Path(args.output).open("w", newline="", encoding="utf-8-sig") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    except requests.RequestException as error:
        print(f"Erro ao consultar a API do Intercom: {error}", file=sys.stderr)
        return 1

    print(f"Relatório gerado: {args.output} ({len(rows)} mesclagem(ns)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

