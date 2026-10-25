"""Create the reviewed endpoint catalog with byte/character offsets into public bundles."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = "chunk-QD3Q3KF7.js"
ROWS = [
    (
        "list_collections",
        "GET",
        "services",
        "/collections",
        None,
        "collections",
        "query(e){return this.http.get(`${w1.baseUrls.services}/collections`)",
    ),
    (
        "list_lists",
        "GET",
        "sync",
        "/collections/{collection_id}/lists",
        None,
        "lists",
        "query(e){let r=`${w1.baseUrls.sync}/collections/${e.collection_id}/lists`",
    ),
    (
        "list_items",
        "GET",
        "sync",
        "/collections/{collection_id}/items",
        None,
        "items",
        "itemsEndpointUrl(e){",
    ),
    (
        "list_list_items",
        "GET",
        "sync",
        "/collections/{collection_id}/lists/{list_id}/items",
        None,
        "items",
        "itemsEndpointUrl(e){",
    ),
    (
        "get_item",
        "GET",
        "sync",
        "/collections/{collection_id}/items/{item_id}",
        None,
        "item",
        "get(e,r){let n=`${w1.baseUrls.sync}/collections/${e}/items/${r}`",
    ),
    (
        "create_collection",
        "POST",
        "services",
        "/collections",
        "{name: string}",
        "collection",
        "post(e){let r=`${w1.baseUrls.services}/collections`",
    ),
    (
        "create_item",
        "POST",
        "sync",
        "/collections/{collection_id}/items",
        "{item: metadata}",
        "item",
        "post(e,r){let n=`${w1.baseUrls.sync}/collections/${e}/items`",
    ),
    (
        "import_identifier",
        "POST",
        "sync",
        "/collections/{collection_id}/items",
        "{ext_ids:{doi|pmid:string},merge:boolean,resolve:boolean,resolve_files:boolean}",
        "item",
        "add(e,r,n,a,s){",
    ),
    (
        "update_metadata",
        "PATCH",
        "sync",
        "/collections/{collection_id}/items/{item_id}",
        "{item: metadata}",
        "item",
        "patch(e,r,n){let a=`${w1.baseUrls.sync}/collections/${e}/items/${r}`",
    ),
    (
        "update_notes",
        "POST",
        "sync",
        "/collections/{collection_id}/items/{item_id}/set_notes",
        "{notes:string}",
        "item",
        "updateNotes(e,r,n){",
    ),
    (
        "set_tags",
        "POST",
        "sync",
        "/collections/{collection_id}/items/{item_id}/set_tags",
        "{tags:string[]}",
        "item",
        "setTags(e,r,n){",
    ),
    (
        "add_tags",
        "POST",
        "sync",
        "/collections/{collection_id}/items/{item_id}/add_tags",
        "{tags:string[]}",
        "item",
        "addTags(e,r,n){",
    ),
    (
        "remove_tags",
        "POST",
        "sync",
        "/collections/{collection_id}/items/{item_id}/remove_tags",
        "{tags:string[]}",
        "item",
        "removeTags(e,r,n){",
    ),
    (
        "delete_item",
        "DELETE",
        "sync",
        "/collections/{collection_id}/items/{item_id}",
        None,
        "item",
        "delete(e,r){let n=`${w1.baseUrls.sync}/collections/${e}/items/${r}`",
    ),
    (
        "get_annotations",
        "GET",
        "sync",
        "/collections/{collection_id}/items/{item_id}/annotations",
        None,
        "annotations",
        "annotations(e,r){",
    ),
    (
        "update_annotation",
        "PATCH",
        "sync",
        "/collections/{collection_id}/items/{item_id}/annotations/{annotation_id}",
        "raw patch object",
        None,
        "patchAnnotation(e,r,n,a){",
    ),
    (
        "delete_annotation",
        "DELETE",
        "sync",
        "/collections/{collection_id}/items/{item_id}/annotations/{annotation_id}",
        None,
        None,
        "deleteAnnotation(e,r,n){",
    ),
    (
        "create_list",
        "POST",
        "sync",
        "/collections/{collection_id}/lists",
        "{list:{id,collection_id,name,parent_id}}",
        "list",
        "post(e){let r=`${w1.baseUrls.sync}/collections/${e.collection_id}/lists`",
    ),
    (
        "rename_list",
        "PATCH",
        "sync",
        "/collections/{collection_id}/lists/{list_id}",
        "{list:{id,collection_id,name}}",
        "list",
        "patch(e){let r=`${w1.baseUrls.sync}/collections/${e.collection_id}/lists/${e.id}`",
    ),
    (
        "delete_list",
        "DELETE",
        "sync",
        "/collections/{collection_id}/lists/{list_id}",
        None,
        "list",
        "delete(e,r){let n=`${w1.baseUrls.sync}/collections/${e}/lists/${r}`",
    ),
    (
        "add_to_list",
        "POST",
        "sync",
        "/collections/{collection_id}/lists/{list_id}/add_items",
        "{item_ids:string[]}",
        "list",
        "addItems(e,r,n){",
    ),
    (
        "remove_from_list",
        "POST",
        "sync",
        "/collections/{collection_id}/lists/{list_id}/remove_items",
        "{item_ids:string[]}",
        "list",
        "removeItems(e,r,n){",
    ),
    (
        "add_file",
        "POST",
        "sync",
        "/collections/{collection_id}/items/{item_id}/add_file",
        "{file_name,file_size,hash,primary:false,resolve:false,skip_resolve:true,merge:false}",
        None,
        "addFile(e,r,n){",
    ),
    (
        "upload_file",
        "POST",
        "sync",
        "/collections/{collection_id}/items/upload_file",
        "{file_name,file_size,hash,list_id?,resolve:true,skip_resolve:false,merge:true}",
        None,
        "uploadFile(e,r){let n=`${w1.baseUrls.sync}",
    ),
    (
        "uploads_pending",
        "GET",
        "sync",
        "/collections/{collection_id}/items/uploads_pending",
        None,
        None,
        "uploadsPending(e){",
    ),
    (
        "get_revisions",
        "GET",
        "sync",
        "/collections/{collection_id}/items/{item_id}/revisions",
        None,
        "revisions",
        "getRevisions(e,r){return this.http.get(",
    ),
]

ROWS += [
    (
        "list_smartlists",
        "GET",
        "sync",
        "/collections/{collection_id}/smartlists",
        None,
        "smartlists",
        "query(e){let r=`${w1.baseUrls.sync}/collections/${e.collection_id}/smartlists`",
    ),
    (
        "get_smartlist",
        "GET",
        "sync",
        "/collections/{collection_id}/smartlists/{smartlist_id}",
        None,
        "smartlist",
        "get(e,r){let n=`${w1.baseUrls.sync}/collections/${e}/smartlists/${r}`",
    ),
    (
        "create_smartlist",
        "POST",
        "sync",
        "/collections/{collection_id}/smartlists",
        "{smartlist:{id,collection_id,name,query,sort?,search_mode?}}",
        "smartlist",
        "post(e){let r=`${w1.baseUrls.sync}/collections/${e.collection_id}/smartlists`",
    ),
    (
        "update_smartlist",
        "PATCH",
        "sync",
        "/collections/{collection_id}/smartlists/{smartlist_id}",
        "{smartlist:{id,collection_id,name?,query?,sort?,search_mode?}}",
        "smartlist",
        "patch(e){let r=`${w1.baseUrls.sync}/collections/${e.collection_id}/smartlists/${e.id}`",
    ),
    (
        "delete_smartlist",
        "DELETE",
        "sync",
        "/collections/{collection_id}/smartlists/{smartlist_id}",
        None,
        "smartlist",
        "delete(e,r){let n=`${w1.baseUrls.sync}/collections/${e}/smartlists/${r}`",
    ),
    (
        "set_primary_file",
        "POST",
        "sync",
        "/collections/{collection_id}/items/{item_id}/set_primary",
        "{hash:sha256}",
        "item",
        "setPrimary(e,r,n){let a=`${w1.baseUrls.sync}",
    ),
]


def main():
    s = (ROOT / "research/sources" / CORE).read_text()
    catalog = {}
    for name, method, host, path, body, response, needle in ROWS:
        offset = s.find(needle)
        if offset < 0:
            raise RuntimeError(f"Missing source: {name}")
        catalog[name] = {
            "method": method,
            "host": host,
            "path": path,
            "body_contract": body,
            "response_key": response,
            "evidence": "SOURCE_CONFIRMED",
            "verification": "UNVERIFIED",
            "discovered": "2026-10-24",
            "frontend_version": "5.4.24",
            "source": {
                "url": "https://app.readcube.com/" + CORE,
                "character_offset": offset,
                "needle": needle,
            },
        }
    catalog["create_annotation"] = {
        "method": "POST",
        "host": "sync",
        "path": "/collections/{collection_id}/bulk_single",
        "body_contract": "{type:item,action_name:add_annotation,data:[{id:item_id,data:note_or_single_page_highlight}]}",
        "response_key": None,
        "evidence": "SOURCE_CONFIRMED",
        "verification": "UNVERIFIED",
        "discovered": "2026-10-25",
        "frontend_version": "5.4.24",
        "source": {
            "url": "https://app.readcube.com/" + CORE,
            "character_offset": s.index("bulkCreateAnnotations(e,r,n)"),
        },
    }
    catalog["import_identifier"]["body_contract"] = (
        "{ext_ids:{doi:string},merge:true,resolve:true,resolve_files:false}"
    )
    catalog["import_pmid"] = {
        **catalog["import_identifier"],
        "body_contract": "{ext_ids:{pmid:string},merge:true,resolve:true,resolve_files:false}",
    }
    catalog["upload_pdf_flow"] = {
        "evidence": "SOURCE_CONFIRMED",
        "verification": "UNVERIFIED",
        "method": "FLOW",
        "host": "sync",
        "path": "/collections/{collection_id}/items/{item_id}/add_file",
        "body_contract": "SHA256 -> add_file -> PUT upload_url -> uploads_pending -> add_file -> GET hash",
        "source": {"url": "https://app.readcube.com/chunk-JCLW3CJS.js", "character_offset": 858000},
        "response_key": None,
        "discovered": "2026-10-24",
        "frontend_version": "5.4.24",
    }
    catalog["import_pdf_flow"] = {
        **catalog["upload_pdf_flow"],
        "path": "/collections/{collection_id}/items/upload_file",
        "body_contract": "SHA256 -> upload_file -> PUT upload_url -> uploads_pending -> upload_file -> GET hash",
    }
    catalog["reader_metadata"] = {
        "method": "GET",
        "host": "services",
        "path": "/reader/metadata",
        "body_contract": "query doi=canonical DOI",
        "response_key": "meta",
        "evidence": "SOURCE_CONFIRMED",
        "verification": "UNVERIFIED",
        "discovered": "2026-10-25",
        "frontend_version": "historical; live checked separately",
        "source": {
            "url": "https://blog.hxgpark.com/posts/ReadCubePapersAPI/",
            "needle": "/reader/metadata",
        },
    }
    catalog["watch_changes"] = {
        "method": "FLOW",
        "host": "push",
        "path": "/bayeux",
        "body_contract": "GET JSONP handshake -> WSS connect/subscribe -> /production/collections/{collection_id}/changes; full scan recovery",
        "response_key": None,
        "evidence": "SOURCE_CONFIRMED",
        "verification": "UNVERIFIED",
        "discovered": "2026-10-25",
        "frontend_version": "5.4.24",
        "source": {"url": "https://app.readcube.com/" + CORE, "character_offset": 2340179},
    }
    (ROOT / "readcube_client/endpoints.json").write_text(json.dumps(catalog, indent=2) + "\n")
    (ROOT / "research/phase-1-2.json").write_text(
        json.dumps(
            {
                "date": "2026-10-24",
                "source_repo_commit": "38e35f4089f720560724537be764685294098e73",
                "gist_revision": "aa97173f59786b759c73cd71ced261c3fe97e011",
                "current_version": "5.4.24",
                "confirmed_contracts": len(ROWS),
                "unresolved": [
                    "SSO/MFA and forced CSRF login branches",
                    "durable server delta cursor not established",
                    "subscription, size and non-PDF upload limits",
                    "shared and read-only role permission matrix",
                    "concurrent conditional writes",
                ],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
