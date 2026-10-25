"""Read existing DOI and preview a note update; never modifies the server."""

from readcube_client import ReadCubeClient, Settings


def main():
    settings = Settings.from_toml("readcube.local.toml")
    with ReadCubeClient(settings) as client:
        collection_id = settings.write_collections[0]
        matches = client.find_by_doi("10.1038/nature12373", collection_id)
        if not matches:
            print(client.import_by_doi(collection_id, "10.1038/nature12373").model_dump_json())
        elif len(matches) > 1:
            print('{"needs_review":true}')
        else:
            plan = client.update_notes(collection_id, matches[0]["id"], "阅读摘要待用户确认")
            print(plan.model_dump_json())


if __name__ == "__main__":
    main()
