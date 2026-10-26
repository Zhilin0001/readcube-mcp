import asyncio
import json
import re
import shutil
import subprocess

import pytest

from readcube_mcp.attachment_ui import HTML, URI
from readcube_mcp.server import create_server


@pytest.mark.parametrize("mode", ["success", "unsupported", "failed"])
def test_native_upload_requires_user_click_and_host_confirmation(mode):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed only for the optional host-widget JavaScript test")
    script = re.search(r"<script>(.*?)</script>", HTML, re.DOTALL).group(1)
    harness = r"""
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {File}=require('node:buffer');global.File=File;
const mode=JSON.parse(process.argv[1]);
const nodes=Object.fromEntries(['attach','status','download','name'].map(id=>[id,{hidden:true,disabled:true,handlers:{},addEventListener(type,fn){this.handlers[type]=fn;}}]));
global.document={getElementById:id=>nodes[id]};
let uploads=0,fetches=0,state;
global.window={addEventListener(){},openai:{toolOutput:{artifact:{name:'paper.pdf',download_url:'https://example.com/artifacts/test'}},setWidgetState:value=>state=value}};
if(mode!=='unsupported')window.openai.uploadFile=async file=>{uploads++;assert.equal(file.name,'paper.pdf');if(mode==='failed')throw new Error('host error');return {fileId:'file_host_confirmed'};};
global.fetch=async (url,options)=>{fetches++;assert.equal(url,'https://example.com/artifacts/test');assert.equal(options.credentials,'omit');return {ok:true,blob:async()=>new Blob(['%PDF-test'],{type:'application/pdf'})};};
vm.runInThisContext(JSON.parse(process.argv[2]));
(async()=>{
 assert.equal(uploads,0);assert.equal(fetches,0);
 if(mode==='unsupported'){assert.equal(nodes.attach.disabled,true);assert.match(nodes.status.textContent,/unavailable/);assert.equal(nodes.download.hidden,false);}
 else {await nodes.attach.handlers.click();assert.equal(uploads,1);if(mode==='success'){assert.equal(state.modelContent.file_id,'file_host_confirmed');assert.match(nodes.status.textContent,/Uploaded to ChatGPT/);}else {assert.equal(state,undefined);assert.match(nodes.status.textContent,/could not be confirmed/);}}
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        [node, "-e", harness, json.dumps(mode), json.dumps(script)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_attachment_tool_links_to_an_available_ui_resource():
    async def run():
        server = create_server(artifact_origin="https://example.com")
        tools = {t.name: t for t in await server.list_tools()}
        assert tools["readcube_prepare_pdf_attachment"].meta["ui"]["resourceUri"] == URI
        resource = next(r for r in await server.list_resources() if str(r.uri) == URI)
        assert resource.meta["ui"]["csp"]["connectDomains"] == ["https://example.com"]
        content = await server.read_resource(URI)
        assert "uploadFile" in content[0].content

    asyncio.run(run())
