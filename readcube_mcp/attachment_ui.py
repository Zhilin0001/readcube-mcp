"""Optional host UI; native file upload runs only after the user presses its button."""

URI = "ui://readcube/pdf-attachment.html"
HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font:14px system-ui;margin:16px;color:light-dark(#17212b,#eef2f6);color-scheme:light dark}button,a{margin:8px 8px 0 0}button{padding:8px 12px;border:1px solid #9ba8b7;border-radius:7px;background:transparent;color:inherit}#status{font-size:13px;opacity:.8}</style>
</head><body><strong id="name">PDF attachment</strong><div><button id="attach" disabled>Attach to ChatGPT</button><a id="download" hidden rel="noreferrer">Download PDF</a></div><p id="status" role="status">Preparing file…</p>
<script>
const button=document.getElementById('attach');
const status=document.getElementById('status');
const link=document.getElementById('download');
function artifact(){return window.openai?.toolOutput?.artifact;}
function render(){
  const a=artifact();if(!a)return;
  document.getElementById('name').textContent=a.name||'PDF attachment';
  const url=a.download_url;
  if(!url||new URL(url).protocol!=='https:'){
    status.textContent='Use the file resource in your local client. Web attachment delivery requires the HTTPS deployment.';return;
  }
  link.href=url;link.hidden=false;
  button.disabled=typeof window.openai?.uploadFile!=='function';
  status.textContent=button.disabled?'This client supports downloads; native ChatGPT upload is unavailable.':'Attach this PDF to ChatGPT, or download the original. The link expires after ten minutes.';
}
button.addEventListener('click',async()=>{
  button.disabled=true;
  try{
    const a=artifact();const url=new URL(a.download_url);
    if(url.protocol!=='https:')throw new Error('unavailable');
    status.textContent='Uploading PDF to ChatGPT…';
    const response=await fetch(url.href,{credentials:'omit',cache:'no-store'});
    if(!response.ok)throw new Error('unavailable');
    const blob=await response.blob();
    const file=new File([blob],a.name||'paper.pdf',{type:'application/pdf'});
    const uploaded=await window.openai.uploadFile(file);
    if(!uploaded?.fileId)throw new Error('unconfirmed');
    window.openai.setWidgetState?.({modelContent:{upload_status:'uploaded',file_id:uploaded.fileId,file_name:a.name},privateContent:{}});
    status.textContent='Uploaded to ChatGPT. You can continue asking about this PDF.';
  }catch(_error){status.textContent='Upload could not be confirmed. Download the PDF or request a fresh attachment link.';button.disabled=false;}
});
window.addEventListener('openai:set_globals',render);
render();
</script></body></html>"""
