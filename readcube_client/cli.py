import argparse
import json

from pydantic import BaseModel

from .client import ReadCubeClient
from .config import Settings
from .errors import ReadCubeError
from .models import WriteAuthorization
from .workflow import append_note, query_library, workflow_status


def emit(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    print(json.dumps(value, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        description="ReadCube verified API client; writes default to dry-run"
    )
    parser.add_argument("--config")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorize-collection")
    parser.add_argument("--confirm-delete")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("capabilities", "collections"):
        sub.add_parser(name)
    p = sub.add_parser("workflow-status")
    p.add_argument("--collection-id")
    p = sub.add_parser("query-library")
    p.add_argument("collection_id")
    p.add_argument("--query", default="")
    p.add_argument("--field", choices=["title", "doi", "pmid", "notes", "tags"], default="title")
    p.add_argument("--read-only", action="store_true")
    p.add_argument("--annotated-only", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--max-age-seconds", type=int, default=300)
    p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("append-note")
    p.add_argument("collection_id")
    p.add_argument("item_id")
    p.add_argument("text")
    for name in ("lists", "items", "sync"):
        p = sub.add_parser(name)
        p.add_argument("collection_id")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--field", choices=["doi", "pmid", "title"], default="title")
    p.add_argument("--collection-id")
    for name in ("get", "annotations", "notes", "tags", "upload", "delete-item"):
        p = sub.add_parser(name)
        p.add_argument("collection_id")
        p.add_argument("item_id")
        if name in ("notes", "tags", "upload"):
            p.add_argument("value", help="Notes text, JSON string array, or local PDF path")
    p = sub.add_parser("add")
    p.add_argument("collection_id")
    p.add_argument("doi")
    for name in ("create-list", "rename-list", "add-to-list", "remove-from-list", "delete-list"):
        p = sub.add_parser(name)
        p.add_argument("collection_id")
        if name != "create-list":
            p.add_argument("list_id")
        if name in ("create-list", "rename-list"):
            p.add_argument("name")
        if name in ("add-to-list", "remove-from-list"):
            p.add_argument("item_id")
    args = parser.parse_args()
    try:
        settings = Settings.from_toml(args.config)
        authorization = WriteAuthorization(
            collection_id=args.authorize_collection or "",
            authorized=bool(args.authorize_collection),
            confirmation=args.confirm_delete,
        )
        writes = {"dry_run": not args.execute, "authorization": authorization}
        with ReadCubeClient(settings) as client:
            cmd = args.command
            if cmd == "capabilities":
                result = client.capabilities()
            elif cmd == "workflow-status":
                result = workflow_status(client, args.collection_id)
            elif cmd == "query-library":
                result = query_library(
                    client,
                    args.collection_id,
                    query=args.query,
                    field=args.field,
                    read_only=args.read_only,
                    annotated_only=args.annotated_only,
                    limit=args.limit,
                    max_age_seconds=args.max_age_seconds,
                    refresh=args.refresh,
                )
            elif cmd == "append-note":
                if args.execute and args.authorize_collection != args.collection_id:
                    raise ValueError("--authorize-collection must match the target collection")
                result = append_note(
                    client,
                    args.collection_id,
                    args.item_id,
                    args.text,
                    authorized=args.authorize_collection == args.collection_id,
                    dry_run=not args.execute,
                )
            elif cmd == "collections":
                result = client.list_collections()
            elif cmd == "lists":
                result = client.list_lists(args.collection_id)
            elif cmd == "items":
                result = client.list_items(args.collection_id)
            elif cmd == "sync":
                result = client.sync_changes(args.collection_id)
            elif cmd == "search":
                result = client.search(
                    args.query, field=args.field, collection_id=args.collection_id
                )
            elif cmd == "get":
                result = client.get_item(args.collection_id, args.item_id)
            elif cmd == "annotations":
                result = client.get_annotations(args.collection_id, args.item_id)
            elif cmd == "add":
                result = client.import_by_doi(args.collection_id, args.doi, **writes)
            elif cmd == "notes":
                result = client.update_notes(args.collection_id, args.item_id, args.value, **writes)
            elif cmd == "tags":
                tags = json.loads(args.value)
                if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                    raise ValueError("Tags must be a JSON string array")
                result = client.update_tags(args.collection_id, args.item_id, tags, **writes)
            elif cmd == "upload":
                result = client.upload_pdf(args.collection_id, args.item_id, args.value, **writes)
            elif cmd == "create-list":
                result = client.create_list(args.collection_id, args.name, **writes)
            elif cmd == "rename-list":
                result = client.rename_list(args.collection_id, args.list_id, args.name, **writes)
            elif cmd == "add-to-list":
                result = client.add_to_list(
                    args.collection_id, args.list_id, args.item_id, **writes
                )
            elif cmd == "remove-from-list":
                result = client.remove_from_list(
                    args.collection_id, args.list_id, args.item_id, **writes
                )
            elif cmd == "delete-list":
                result = client.delete_list(args.collection_id, args.list_id, **writes)
            else:
                result = client.delete_item(args.collection_id, args.item_id, **writes)
            emit(
                {
                    "ok": True,
                    "data": result.model_dump(mode="json")
                    if isinstance(result, BaseModel)
                    else result,
                }
            )
    except (ReadCubeError, ValueError, OSError) as error:
        # Avoid propagating library/network exception representations containing credentials.
        message = (
            str(error) if isinstance(error, (ReadCubeError, ValueError)) else "Local file error"
        )
        emit({"ok": False, "error": {"type": type(error).__name__, "message": message}})
        return 1
    return 0
