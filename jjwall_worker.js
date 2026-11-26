/**
 * jjwall_worker.js — 掘金壁纸 · Cloudflare Worker 版
 *
 * 和 jjwall.py 功能一样，但这个可以直接部署到 Cloudflare 免费跑，
 * 得到一个公网地址，手机浏览器打开就能用，不用电脑、不用 Termux。
 *
 * 部署方法（手机浏览器就能做）：
 *   1. 打开 https://dash.cloudflare.com/ 注册/登录
 *   2. 左边菜单 Workers & Pages → Create → Workers → Create Worker
 *   3. 名字随便填（比如 jjwall）→ Deploy
 *   4. 点 Edit code，把本文件全部内容粘进去，覆盖掉原来的
 *   5. 右上角 Deploy
 *   6. 得到 https://jjwall.你的用户名.workers.dev
 *
 * 接口原理和 Python 版一致：AES-128-CBC，key = WAG0JIUGYALACVJF。
 */

const APPID = "67905222993c2f0001ad0fd6";
const VER = "10.10.1";
const KEY_STR = "WAG0JIUGYALACVJF";
const HOST = "https://min-api.xliii.cn/";
const CDN = "https://min-cdn.xliii.cn/";
const IV_CHARS = "1245380796AQWERTYUIOP SDFGHJKLqwSeasdzxvcfrtgbyhnmjuiklop".replace(/ /g, "");

const ENDPOINTS = {
  home: "miniapi/Product/home",
  recommend: "miniapi/Product/recommend",
  accountData: "miniapi/Product/accountNewData",
  pageIndex: "miniapi/Product/pageIndex",
  albumList: "miniapi/Product/albumList",
  albumData: "miniapi/Product/albumData",
  albumDataPage: "miniapi/Product/albumDataPage",
  singleData: "miniapi/Product/singleData",
  mine: "miniapi/product/mine",
  appUserData: "miniapi/Cash/appUserData",
};

const UA = "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36";

// ---------- AES-128-CBC ----------

const enc = new TextEncoder();
const dec = new TextDecoder();

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function bytesToB64(bytes) {
  let bin = "";
  const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  }
  return btoa(bin);
}

async function importKey() {
  return crypto.subtle.importKey(
    "raw", enc.encode(KEY_STR), { name: "AES-CBC" }, false, ["encrypt", "decrypt"]
  );
}

async function aesEncrypt(plain, ivStr) {
  const key = await importKey();
  const iv = enc.encode(ivStr);
  const ct = await crypto.subtle.encrypt({ name: "AES-CBC", iv }, key, enc.encode(plain));
  return bytesToB64(new Uint8Array(ct));
}

async function aesDecrypt(b64, ivStr) {
  const key = await importKey();
  const iv = enc.encode(ivStr);
  const pt = await crypto.subtle.decrypt({ name: "AES-CBC", iv }, key, b64ToBytes(b64));
  return dec.decode(pt);
}

function randIv() {
  let s = "";
  for (let i = 0; i < 16; i++) {
    s += IV_CHARS[Math.floor(Math.random() * IV_CHARS.length)];
  }
  return s;
}

// ---------- 调接口 ----------

async function api(name, payload) {
  const path = ENDPOINTS[name] || name;
  const body = Object.assign({
    appid: APPID,
    ver: VER,
    unionid: "",
    openid: "",
    min_push: 0,
    scene: 1001,
  }, payload || {});

  const iv = randIv();
  const requestData = await aesEncrypt(JSON.stringify(body), iv);

  const url = HOST + path + "?requestData=" + encodeURIComponent(requestData)
            + "&iv=" + encodeURIComponent(iv);

  const res = await fetch(url, {
    headers: { "User-Agent": UA, "Referer": CDN, "Accept": "application/json" },
  });
  const j = await res.json();

  const d = j && j.data;
  if (d && typeof d === "object" && d.iv && d.data) {
    try {
      return JSON.parse(await aesDecrypt(d.data, d.iv));
    } catch (e) {
      return { _error: String(e) };
    }
  }
  return d === undefined ? j : d;
}

function imgUrl(rel) {
  if (!rel) return "";
  if (rel.indexOf("http") === 0) return rel;
  return CDN + rel.replace(/^\/+/, "");
}

function decorate(it) {
  if (!it || typeof it !== "object") return it;
  const o = Object.assign({}, it);
  o.url_img = imgUrl(it.img);
  o.url_thumb = imgUrl(it.thumb || it.img);
  o.url_preview = imgUrl(it.preview || it.img);
  o.url_download = o.url_img;
  return o;
}

// ---------- 路由 ----------

function json(obj, code = 200) {
  return new Response(JSON.stringify(obj), {
    status: code || 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-store",
    },
  });
}

export default {
  async fetch(request) {
    const u = new URL(request.url);
    const p = u.pathname;
    const q = u.searchParams;

    try {
      if (p === "/" || p === "/index.html") {
        return new Response(PAGE, {
          headers: { "Content-Type": "text/html; charset=utf-8" },
        });
      }
      if (p === "/health") {
        return json({ ok: true, appid: APPID, ver: VER });
      }
      if (p === "/api/home") {
        const d = await api("home", {});
        const data = d && d.data ? d.data : d;
        if (data && data.list) data.list = data.list.map(decorate);
        if (data && data.recommend) {
          data.recommend.forEach(a => { if (a.app_head_img) a.app_head_img = imgUrl(a.app_head_img); });
        }
        return json(data);
      }
      if (p === "/api/list") {
        const page = parseInt(q.get("page") || "1", 10);
        const acc = q.get("acc_id") || "1";
        const d = await api("pageIndex", { page: page, acc_id: acc });
        const data = d && d.data ? d.data : d;
        if (data && data.list) data.list = data.list.map(decorate);
        return json(data);
      }
      if (p === "/api/album") {
        const page = parseInt(q.get("page") || "1", 10);
        const acc = q.get("acc_id") || "1";
        const d = await api("albumList", { page: page, acc_id: acc });
        return json(d && d.data ? d.data : d);
      }
      if (p === "/api/album_data") {
        const page = parseInt(q.get("page") || "1", 10);
        const d = await api("albumDataPage", {
          page: page, alb_id: q.get("alb_id") || "0", acc_id: q.get("acc_id") || "1",
        });
        const data = d && d.data ? d.data : d;
        if (data && data.list) data.list = data.list.map(decorate);
        return json(data);
      }
      if (p === "/api/item") {
        const d = await api("singleData", { res_id: q.get("res_id") || "0" });
        return json(d && d.data ? d.data : d);
      }
      if (p === "/api/raw") {
        let payload = {};
        try { payload = JSON.parse(q.get("json") || "{}"); } catch (e) {}
        return json(await api(q.get("name") || "home", payload));
      }
      return json({ error: "not found", path: p }, 404);
    } catch (e) {
      return json({ error: String(e && e.message || e) }, 500);
    }
  },
};

// ---------- 前端页面（和 Python 版同一套） ----------

const PAGE = `<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>掘金壁纸 · 独立版</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#0f1115;color:#e8e8ec;font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:20;backdrop-filter:blur(14px);background:rgba(15,17,21,.82);border-bottom:1px solid #1e222a}
.hd{padding:12px 16px 8px;display:flex;align-items:center;gap:10px}
.logo{font-size:17px;font-weight:700;background:linear-gradient(90deg,#638dff,#b06bff);-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{font-size:11px;color:#6b7280;margin-left:auto}
.authors{display:flex;gap:10px;padding:12px 16px;overflow-x:auto;scrollbar-width:none;border-bottom:1px solid #1a1e27}
.authors::-webkit-scrollbar{display:none}
.au{flex:0 0 auto;width:64px;text-align:center;cursor:pointer}
.au img{width:52px;height:52px;border-radius:50%;object-fit:cover;border:2px solid #262b36;background:#1a1e27}
.au.on img{border-color:#638dff}
.au span{display:block;font-size:10px;color:#8b93a3;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
main{padding:12px 12px 90px}
.grid{column-count:2;column-gap:10px}
@media(min-width:720px){.grid{column-count:3}}
@media(min-width:1080px){.grid{column-count:4}}
.card{break-inside:avoid;margin-bottom:10px;border-radius:14px;overflow:hidden;background:#171a21;position:relative;cursor:pointer}
.card img{width:100%;display:block;background:#1f242e;min-height:80px}
.card .meta{position:absolute;left:0;right:0;bottom:0;padding:16px 8px 6px;font-size:10px;color:#c9cfdb;background:linear-gradient(transparent,rgba(0,0,0,.72))}
.card .badge{position:absolute;top:6px;right:6px;font-size:9px;padding:2px 6px;border-radius:6px;background:rgba(0,0,0,.6);color:#fff}
.over{position:fixed;inset:0;background:#000;z-index:99;display:none;flex-direction:column}
.over.on{display:flex}
.over .bar{padding:12px 16px;display:flex;gap:10px;align-items:center;background:rgba(0,0,0,.7);position:relative;z-index:2}
.over .bar .t{font-size:13px;color:#aab;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn{padding:7px 14px;border-radius:10px;background:#638dff;color:#fff;font-size:13px;border:none;cursor:pointer}
.btn.ghost{background:#22262f;color:#c9cfdb}
.over .pic{flex:1;overflow:auto;display:flex;align-items:center;justify-content:center;padding:8px}
.over .pic img{max-width:100%;max-height:100%;object-fit:contain}
.empty{text-align:center;color:#5b6270;padding:60px 20px;font-size:13px}
.loading{height:4px;background:linear-gradient(90deg,#638dff,#8b5cf6);position:fixed;top:0;left:0;width:0;transition:width .3s;z-index:50}
#more{display:block;margin:18px auto 0;padding:11px 28px;border-radius:12px;background:#1a1e27;color:#a8aebc;border:1px solid #262b36;font-size:13px}
#more:disabled{opacity:.4}
.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(40,44,54,.96);color:#fff;padding:9px 18px;border-radius:10px;font-size:13px;opacity:0;transition:.25s;pointer-events:none;z-index:200}
.toast.on{opacity:1}
</style></head><body>
<div class="loading" id="bar"></div>
<header>
  <div class="hd"><div class="logo">掘金壁纸</div><div class="sub" id="stat">加载中…</div></div>
  <div class="authors" id="authors"></div>
</header>
<main>
  <div class="grid" id="grid"></div>
  <div class="empty" id="empty" style="display:none">这里还什么都没有</div>
  <button id="more">加载更多</button>
</main>
<div class="over" id="over">
  <div class="bar"><div class="t" id="otitle"></div>
    <button class="btn" id="odl">下载原图</button>
    <button class="btn ghost" id="oclose">关闭</button></div>
  <div class="pic"><img id="oimg" alt=""></div>
</div>
<div class="toast" id="toast"></div>
<script>
const $=s=>document.querySelector(s);
const state={acc:1,page:1,loading:false,end:false,list:[]};
function toast(t){const e=$('#toast');e.textContent=t;e.classList.add('on');clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove('on'),1600);}
function bar(p){$('#bar').style.width=p+'%';if(p>=100)setTimeout(()=>{$('#bar').style.width='0'},300);}
async function get(u){const r=await fetch(u);if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}
async function boot(){
  bar(30);
  try{
    const d=await get('/api/home');bar(70);
    const rec=d.recommend||[], list=d.list||[];
    const box=$('#authors');box.innerHTML='';
    const all=document.createElement('div');all.className='au on';
    all.innerHTML='<div style="width:52px;height:52px;border-radius:50%;background:linear-gradient(135deg,#638dff,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:13px;margin:0 auto;border:2px solid #262b36">全部</div><span>全部</span>';
    all.onclick=()=>pick(1,all);box.appendChild(all);
    rec.slice(0,30).forEach(a=>{
      const el=document.createElement('div');el.className='au';
      el.innerHTML='<img loading="lazy" src="'+a.app_head_img+'"><span>'+(a.app_name||'')+'</span>';
      el.onclick=()=>pick(a.acc_id,el);box.appendChild(el);
    });
    render(list);$('#stat').textContent=list.length+' 张 · 作者 '+rec.length;bar(100);
  }catch(e){bar(100);$('#empty').style.display='block';$('#empty').textContent='加载失败：'+e.message;}
}
function pick(id,el){[...$('#authors').children].forEach(x=>x.classList.remove('on'));if(el)el.classList.add('on');
  state.acc=id;state.page=1;state.end=false;$('#grid').innerHTML='';state.list=[];loadPage();}
function render(items){
  const g=$('#grid');
  items.forEach(it=>{
    const c=document.createElement('div');c.className='card';
    const src=it.url_thumb||it.url_img,date=(it.date||'').slice(0,10);
    c.innerHTML='<img loading="lazy" src="'+src+'">'+(it.class===4?'<div class="badge">图集</div>':'')+'<div class="meta">'+date+' · #'+it.res_id+'</div>';
    c.onclick=()=>openBig(it);g.appendChild(c);
  });
  $('#empty').style.display=(state.list.length===0&&!state.loading)?'block':'none';
  $('#empty').textContent=state.end&&state.list.length===0?'这个作者还没有图':'这里还什么都没有';
}
async function loadPage(){
  if(state.loading||state.end)return;
  state.loading=true;$('#more').disabled=true;$('#more').textContent='加载中…';bar(40);
  try{
    const d=await get('/api/list?page='+state.page+'&acc_id='+state.acc);
    const list=d.list||[];
    if(list.length===0)state.end=true;
    else{state.list=state.list.concat(list);render(list);state.page++;}
  }catch(e){toast('加载失败：'+e.message);}
  state.loading=false;bar(100);$('#more').disabled=false;
  $('#more').textContent=state.end?'没有更多了':'加载更多';
  $('#stat').textContent=state.list.length+' 张';
}
function openBig(it){
  const u=it.url_img||it.url_preview;
  $('#oimg').src=it.url_preview||u;
  $('#otitle').textContent='#'+it.res_id+' · '+(it.date||'').slice(0,10);
  $('#odl').onclick=()=>{const a=document.createElement('a');a.href=u;a.download='jj_'+it.res_id+'.jpg';a.target='_blank';document.body.appendChild(a);a.click();a.remove();toast('已触发下载，长按图片也可保存');};
  $('#over').classList.add('on');
}
$('#oclose').onclick=()=>$('#over').classList.remove('on');
$('#over').onclick=e=>{if(e.target.id==='over')$('#over').classList.remove('on');};
$('#more').onclick=loadPage;
boot().then(()=>loadPage());
addEventListener('scroll',()=>{if(state.loading||state.end)return;if(innerHeight+scrollY>document.body.offsetHeight-600)loadPage();});
</script></body></html>`;
