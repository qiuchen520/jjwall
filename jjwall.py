#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jjwall.py — 掘金壁纸 · 独立版

脱离小红书，直接用它的接口跑一个自己的壁纸站。

原理（全部来自反编译的 service.js）：

    API:      https://min-api.xliii.cn/
    请求加密:  AES-128-CBC
               key = "WAG0JIUGYALACVJF"
               iv  = 16 位随机串（从固定字符表里抽）
               明文 = {"appid":..., "ver":..., "scene":..., ...业务参数}
               密文 base64 后放进 query 的 requestData，iv 放 query
    响应解密:  data.data 用 data.iv 解，同样的 key
    图片:     https://min-cdn.xliii.cn/ + img / thumb / preview

服务端没有 CORS 头，所以必须由本程序代理，浏览器不能直接调。

用法（零依赖，Python 3.7+ 直接跑）：
    python3 jjwall.py           # 默认 8700
    python jjwall.py 9000       # 自定义端口

然后手机/电脑浏览器打开 http://127.0.0.1:8700
"""
import base64
import json
import os
import random
import re
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import urllib.request
import urllib.error



# ---------------------------------------------------------------- 常量

APPID = "67905222993c2f0001ad0fd6"
VER = "10.10.1"
KEY = b"WAG0JIUGYALACVJF"
HOST = "https://min-api.xliii.cn/"
CDN = "https://min-cdn.xliii.cn/"

# 从 service.js 的 l() 函数原样搬过来的字符表
IV_CHARS = list("1245380796AQWERTYUIOP"
                "SDFGHJKLqwSeasdzxvcfrtgbyhnmjuiklop".replace(" ", ""))

UA = ("Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36")

# service.js 里登记的全部接口
ENDPOINTS = {
    "home":          ("miniapi/Product/home", "首页列表"),
    "recommend":     ("miniapi/Product/recommend", "推荐数据"),
    "accountData":   ("miniapi/Product/accountNewData", "用户账号数据"),
    "pageIndex":     ("miniapi/Product/pageIndex", "分页数据"),
    "albumList":     ("miniapi/Product/albumList", "专辑列表"),
    "albumData":     ("miniapi/Product/albumData", "单专辑信息"),
    "albumDataPage": ("miniapi/Product/albumDataPage", "单专辑分页"),
    "singleData":    ("miniapi/Product/singleData", "单张图资源"),
    "mine":          ("miniapi/product/mine", "个人中心"),
    "appUserData":   ("miniapi/Cash/appUserData", "用户初始化"),
    "goodsList":     ("miniapi/Order/goodsList", "商品列表"),
    "rankList":      ("miniapi/Product/rankList", "排行榜"),
}



# ---------------------------------------------------------------- 纯 Python AES（Termux 兜底）

try:
    from Crypto.Cipher import AES as _AES
    from Crypto.Util.Padding import pad as _pad, unpad as _unpad
    _HAVE_PYC = True
except ImportError:
    _HAVE_PYC = False

if os.environ.get("JJWALL_PURE") == "1":
    _HAVE_PYC = False   # 强制走纯 Python 实现，方便在没装 pycryptodome 的机器上验证

_SBOX = [
0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16]

_INV = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV[_v] = _i

_RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1b) & 0xff
    return a


def _mul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        b >>= 1
        a = _xtime(a)
    return r


def _expand(key):
    nk = 4
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 44):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // nk - 1]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(11)]


def _add_key(st, rk):
    return [st[i] ^ rk[i] for i in range(16)]


def _shift_rows(st):
    out = [0] * 16
    for r in range(4):
        for c in range(4):
            out[r + 4 * c] = st[r + 4 * ((c + r) % 4)]
    return out


def _mix_cols(st):
    ns = []
    for c in range(4):
        a = st[4 * c:4 * c + 4]
        ns += [
            _mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3],
            a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3],
            a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3),
            _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2),
        ]
    return ns


def _inv_mix_cols(st):
    ns = []
    for c in range(4):
        a = st[4 * c:4 * c + 4]
        ns += [
            _mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9),
            _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13),
            _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11),
            _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14),
        ]
    return ns


def _enc_block(blk, rks):
    st = _add_key(blk, rks[0])
    for rnd in range(1, 11):
        st = [_SBOX[b] for b in st]
        st = _shift_rows(st)
        if rnd != 10:
            st = _mix_cols(st)
        st = _add_key(st, rks[rnd])
    return st


def _inv_shift(st):
    out = [0] * 16
    for r in range(4):
        for c in range(4):
            out[r + 4 * c] = st[r + 4 * ((c - r) % 4)]
    return out


def _dec_block(blk, rks):
    st = _add_key(blk, rks[10])
    for rnd in range(9, -1, -1):
        st = _inv_shift(st)
        st = [_INV[b] for b in st]
        st = _add_key(st, rks[rnd])
        if rnd != 0:
            st = _inv_mix_cols(st)
    return st


def _pure_encrypt(data, key, iv):
    rks = _expand(list(key))
    out = bytearray()
    prev = list(iv)
    for i in range(0, len(data), 16):
        blk = [data[i + j] ^ prev[j] for j in range(16)]
        prev = _enc_block(blk, rks)
        out += bytes(prev)
    return bytes(out)


def _pure_decrypt(data, key, iv):
    rks = _expand(list(key))
    out = bytearray()
    prev = list(iv)
    for i in range(0, len(data), 16):
        blk = list(data[i:i + 16])
        pt = _dec_block(blk, rks)
        out += bytes([pt[j] ^ prev[j] for j in range(16)])
        prev = blk
    return bytes(out)


def _pkcs7(b):
    n = 16 - (len(b) % 16)
    return b + bytes([n]) * n


def _unpkcs7(b):
    if not b:
        return b
    n = b[-1]
    return b[:-n] if 0 < n <= 16 else b


def rand_iv():
    return "".join(random.choice(IV_CHARS) for _ in range(16))


def aes_encrypt(obj, iv):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    if _HAVE_PYC:
        c = _AES.new(KEY, _AES.MODE_CBC, iv.encode())
        return base64.b64encode(c.encrypt(_pad(raw, 16))).decode()
    ct = _pure_encrypt(_pkcs7(raw), KEY, iv.encode())
    return base64.b64encode(ct).decode()


def aes_decrypt(b64, iv):
    data = base64.b64decode(b64)
    if _HAVE_PYC:
        c = _AES.new(KEY, _AES.MODE_CBC, iv.encode())
        return _unpad(c.decrypt(data), 16).decode("utf-8", "ignore")
    pt = _unpkcs7(_pure_decrypt(data, KEY, iv.encode()))
    return pt.decode("utf-8", "ignore")


# ---------------------------------------------------------------- 客户端

_HEADERS = {
    "User-Agent": UA,
    "Referer": CDN,
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "identity",
}


def http_get(url, timeout=25):
    """零依赖 GET，返回 (status, text)。"""
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")


def api(name_or_path, payload=None, timeout=20):
    """调一个接口，自动加解密。返回解密后的 data 对象。"""
    path = ENDPOINTS[name_or_path][0] if name_or_path in ENDPOINTS else name_or_path
    body = dict(payload or {})
    # service.js 里这些字段是塞进加密体里的，不是 query
    body.setdefault("appid", APPID)
    body.setdefault("ver", VER)
    body.setdefault("unionid", "")
    body.setdefault("openid", "")
    body.setdefault("min_push", 0)
    body.setdefault("scene", 1001)

    iv = rand_iv()
    qs = urllib.parse.urlencode({"requestData": aes_encrypt(body, iv), "iv": iv})
    status, text = http_get(HOST + path + "?" + qs, timeout=timeout)
    if status != 200:
        raise IOError("上游 HTTP %d：%s" % (status, text[:200]))
    j = json.loads(text)

    d = j.get("data")
    if isinstance(d, dict) and d.get("iv") and d.get("data"):
        plain = aes_decrypt(d["data"], d["iv"])
        try:
            return json.loads(plain)
        except Exception:
            return {"_raw": plain}
    return d if d is not None else j


def img_url(rel, kind="img"):
    """把接口里的相对路径拼成 CDN 地址。"""
    if not rel:
        return ""
    if rel.startswith("http"):
        return rel
    return CDN + rel.lstrip("/")


def decorate(item):
    """给一张图补上可直接访问的三个尺寸。"""
    if not isinstance(item, dict):
        return item
    out = dict(item)
    out["url_img"] = img_url(item.get("img"))
    out["url_thumb"] = img_url(item.get("thumb") or item.get("img"))
    out["url_preview"] = img_url(item.get("preview") or item.get("img"))
    out["url_download"] = out["url_img"]
    if item.get("video_url"):
        out["url_video"] = img_url(item["video_url"])
    return out


# ---------------------------------------------------------------- 前端页面

PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>掘金壁纸 · 独立版</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#0f1115;color:#e8e8ec;
     font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:20;backdrop-filter:blur(14px);
       background:rgba(15,17,21,.82);border-bottom:1px solid #1e222a}
.hd{padding:12px 16px 8px;display:flex;align-items:center;gap:10px}
.logo{font-size:17px;font-weight:700;background:linear-gradient(90deg,#638dff,#b06bff);
      -webkit-background-clip:text;background-clip:text;color:transparent}
.sub{font-size:11px;color:#6b7280;margin-left:auto}
.tabs{display:flex;gap:8px;padding:0 16px 12px;overflow-x:auto;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{flex:0 0 auto;padding:7px 14px;border-radius:999px;background:#1a1e27;
     color:#a8aebc;font-size:13px;border:1px solid #262b36;cursor:pointer;
     transition:.15s;white-space:nowrap}
.tab.on{background:linear-gradient(135deg,#638dff,#8b5cf6);color:#fff;border-color:transparent}
.authors{display:flex;gap:10px;padding:12px 16px;overflow-x:auto;scrollbar-width:none;
         border-bottom:1px solid #1a1e27}
.authors::-webkit-scrollbar{display:none}
.au{flex:0 0 auto;width:64px;text-align:center;cursor:pointer}
.au img{width:52px;height:52px;border-radius:50%;object-fit:cover;
        border:2px solid #262b36;background:#1a1e27}
.au.on img{border-color:#638dff}
.au span{display:block;font-size:10px;color:#8b93a3;margin-top:4px;
         overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
main{padding:12px 12px 90px}
.grid{column-count:2;column-gap:10px}
@media(min-width:720px){.grid{column-count:3}}
@media(min-width:1080px){.grid{column-count:4}}
.card{break-inside:avoid;margin-bottom:10px;border-radius:14px;overflow:hidden;
      background:#171a21;position:relative;cursor:pointer}
.card img{width:100%;display:block;background:#1f242e;min-height:80px}
.card .meta{position:absolute;left:0;right:0;bottom:0;padding:16px 8px 6px;
            font-size:10px;color:#c9cfdb;
            background:linear-gradient(transparent,rgba(0,0,0,.72))}
.card .badge{position:absolute;top:6px;right:6px;font-size:9px;padding:2px 6px;
             border-radius:6px;background:rgba(0,0,0,.6);color:#fff}
.over{position:fixed;inset:0;background:#000;z-index:99;display:none;
      flex-direction:column}
.over.on{display:flex}
.over .bar{padding:12px 16px;display:flex;gap:10px;align-items:center;
           background:rgba(0,0,0,.7);position:relative;z-index:2}
.over .bar .t{font-size:13px;color:#aab;flex:1;overflow:hidden;
              text-overflow:ellipsis;white-space:nowrap}
.btn{padding:7px 14px;border-radius:10px;background:#638dff;color:#fff;
     font-size:13px;border:none;cursor:pointer}
.btn.ghost{background:#22262f;color:#c9cfdb}
.over .pic{flex:1;overflow:auto;display:flex;align-items:center;justify-content:center;
           padding:8px}
.over .pic img{max-width:100%;max-height:100%;object-fit:contain}
.empty{text-align:center;color:#5b6270;padding:60px 20px;font-size:13px}
.loading{height:4px;background:linear-gradient(90deg,#638dff,#8b5cf6);
         position:fixed;top:0;left:0;width:0;transition:width .3s;z-index:50}
#more{display:block;margin:18px auto 0;padding:11px 28px;border-radius:12px;
      background:#1a1e27;color:#a8aebc;border:1px solid #262b36;font-size:13px}
#more:disabled{opacity:.4}
.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);
       background:rgba(40,44,54,.96);color:#fff;padding:9px 18px;border-radius:10px;
       font-size:13px;opacity:0;transition:.25s;pointer-events:none;z-index:200}
.toast.on{opacity:1}
</style>
</head>
<body>
<div class="loading" id="bar"></div>

<header>
  <div class="hd">
    <div class="logo">掘金壁纸</div>
    <div class="sub" id="stat">加载中…</div>
  </div>
  <div class="tabs" id="tabs"></div>
  <div class="authors" id="authors"></div>
</header>

<main>
  <div class="grid" id="grid"></div>
  <div class="empty" id="empty" style="display:none">这里还什么都没有</div>
  <button id="more">加载更多</button>
</main>

<div class="over" id="over">
  <div class="bar">
    <div class="t" id="otitle"></div>
    <button class="btn" id="odl">下载原图</button>
    <button class="btn ghost" id="oclose">关闭</button>
  </div>
  <div class="pic"><img id="oimg" alt=""></div>
</div>

<div class="toast" id="toast"></div>

<script>
const $ = s => document.querySelector(s);
const state = { acc: 1, page: 1, loading: false, end: false, list: [] };

function toast(t){
  const el = $('#toast'); el.textContent = t; el.classList.add('on');
  clearTimeout(el._t); el._t = setTimeout(()=>el.classList.remove('on'), 1600);
}
function bar(p){ $('#bar').style.width = p + '%'; if(p>=100) setTimeout(()=>{ $('#bar').style.width='0'},300); }

async function get(u){
  const r = await fetch(u);
  if(!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

// ---- 首页 ----
async function boot(){
  bar(30);
  try{
    const d = await get('/api/home');
    bar(70);
    const rec = (d.recommend || []);
    const list = (d.list || []);

    // 作者条
    const box = $('#authors'); box.innerHTML = '';
    const allBtn = document.createElement('div');
    allBtn.className = 'au on';
    allBtn.innerHTML = '<div style="width:52px;height:52px;border-radius:50%;background:linear-gradient(135deg,#638dff,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:13px;margin:0 auto;border:2px solid #262b36">全部</div><span>全部</span>';
    allBtn.onclick = () => pickAcc(1, allBtn);
    box.appendChild(allBtn);

    rec.slice(0,20).forEach(a => {
      const el = document.createElement('div');
      el.className = 'au';
      el.innerHTML = `<img src="${a.app_head_img}" loading="lazy"><span>${a.app_name||''}</span>`;
      el.onclick = () => pickAcc(a.acc_id, el);
      box.appendChild(el);
    });

    // 分类 tab
    const tabs = ['全部','壁纸','头像','套图'];
    const tb = $('#tabs'); tb.innerHTML = '';
    tabs.forEach((t,i)=>{
      const el = document.createElement('div');
      el.className = 'tab' + (i===0?' on':'');
      el.textContent = t;
      el.onclick = ()=>{ [...tb.children].forEach(x=>x.classList.remove('on')); el.classList.add('on'); };
      tb.appendChild(el);
    });

    render(list);
    $('#stat').textContent = list.length + ' 张 · 作者 ' + rec.length;
    bar(100);
  }catch(e){
    bar(100);
    $('#empty').style.display='block';
    $('#empty').textContent = '加载失败：' + e.message;
  }
}

function pickAcc(id, el){
  [...$('#authors').children].forEach(x=>x.classList.remove('on'));
  if(el) el.classList.add('on');
  state.acc = id; state.page = 1; state.end = false;
  $('#grid').innerHTML = ''; state.list = [];
  loadPage();
}

function render(items){
  const g = $('#grid');
  items.forEach((it, i) => {
    const c = document.createElement('div');
    c.className = 'card';
    const src = it.url_thumb || it.url_img;
    const date = (it.date||'').slice(0,10);
    c.innerHTML = `<img loading="lazy" src="${src}" alt="">
      ${it.class===4?'<div class="badge">图集</div>':''}
      <div class="meta">${date} · #${it.res_id}</div>`;
    c.onclick = () => openBig(it);
    g.appendChild(c);
  });
  $('#empty').style.display = (state.list.length===0 && !state.loading) ? 'block':'none';
  $('#empty').textContent = state.end && state.list.length===0 ? '这个作者还没有图' : '这里还什么都没有';
}

// ---- 分页 ----
async function loadPage(){
  if(state.loading || state.end) return;
  state.loading = true;
  $('#more').disabled = true; $('#more').textContent = '加载中…';
  bar(40);
  try{
    const d = await get(`/api/list?page=${state.page}&acc_id=${state.acc}`);
    const list = (d.list || []);
    if(list.length === 0){ state.end = true; }
    else {
      state.list = state.list.concat(list);
      render(list);
      state.page++;
    }
  }catch(e){ toast('加载失败：'+e.message); }
  state.loading = false; bar(100);
  $('#more').disabled = false;
  $('#more').textContent = state.end ? '没有更多了' : '加载更多';
  $('#stat').textContent = state.list.length + ' 张';
}

function openBig(it){
  const u = it.url_img || it.url_preview;
  $('#oimg').src = it.url_preview || u;
  $('#otitle').textContent = `#${it.res_id} · ${(it.date||'').slice(0,10)}`;
  $('#odl').onclick = () => {
    const a = document.createElement('a');
    a.href = u; a.download = `jj_${it.res_id}.jpg`;
    a.target = '_blank'; a.rel='noopener';
    document.body.appendChild(a); a.click(); a.remove();
    toast('已触发下载，长按图片也可保存');
  };
  $('#over').classList.add('on');
}
$('#oclose').onclick = () => $('#over').classList.remove('on');
$('#over').onclick = e => { if(e.target.id==='over') $('#over').classList.remove('on'); };
$('#more').onclick = loadPage;

boot().then(()=>loadPage());
window.addEventListener('scroll', ()=>{
  if(state.loading || state.end) return;
  if(window.innerHeight + scrollY > document.body.offsetHeight - 600) loadPage();
});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "jjwall/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)

        def arg(k, d=None):
            v = q.get(k)
            return v[0] if v else d

        try:
            if u.path in ("/", "/index.html"):
                self._send(200, PAGE, "text/html; charset=utf-8")
                return

            if u.path == "/api/home":
                d = api("home")
                data = d.get("data", d) if isinstance(d, dict) else d
                if isinstance(data, dict):
                    data["list"] = [decorate(x) for x in data.get("list", [])]
                    for a in data.get("recommend", []):
                        if isinstance(a, dict) and a.get("app_head_img"):
                            a["app_head_img"] = img_url(a["app_head_img"])
                self._json(data)
                return

            if u.path == "/api/list":
                page = int(arg("page", "1"))
                acc = arg("acc_id", "1")
                d = api("pageIndex", {"page": page, "acc_id": acc})
                data = d.get("data", d) if isinstance(d, dict) else d
                if isinstance(data, dict):
                    data["list"] = [decorate(x) for x in data.get("list", [])]
                self._json(data)
                return

            if u.path == "/api/album":
                page = int(arg("page", "1"))
                acc = arg("acc_id", "1")
                d = api("albumList", {"page": page, "acc_id": acc})
                data = d.get("data", d) if isinstance(d, dict) else d
                self._json(data)
                return

            if u.path == "/api/album_data":
                page = int(arg("page", "1"))
                alb = arg("alb_id", "0")
                acc = arg("acc_id", "1")
                d = api("albumDataPage", {"page": page, "alb_id": alb, "acc_id": acc})
                data = d.get("data", d) if isinstance(d, dict) else d
                if isinstance(data, dict):
                    data["list"] = [decorate(x) for x in data.get("list", [])]
                self._json(data)
                return

            if u.path == "/api/item":
                rid = arg("res_id", "0")
                d = api("singleData", {"res_id": rid})
                data = d.get("data", d) if isinstance(d, dict) else d
                if isinstance(data, dict) and isinstance(data.get("data"), dict):
                    data["data"] = decorate(data["data"])
                self._json(data)
                return

            if u.path == "/api/raw":
                name = arg("name", "home")
                payload = {}
                if arg("json"):
                    try:
                        payload = json.loads(arg("json"))
                    except Exception:
                        pass
                self._json(api(name, payload))
                return

            if u.path == "/api/endpoints":
                self._json({k: {"path": v[0], "desc": v[1]}
                            for k, v in ENDPOINTS.items()})
                return

            if u.path == "/health":
                self._json({"ok": True, "appid": APPID, "ver": VER})
                return

            self._send(404, json.dumps({"error": "not found"}), )
        except urllib.error.HTTPError as e:
            self._json({"error": "upstream " + str(e)}, 502)
        except Exception as e:
            self._json({"error": "%s: %s" % (type(e).__name__, e)}, 500)


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    port = 8700
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    ip = lan_ip()
    print("=" * 56)
    print("  掘金壁纸 · 独立版")
    print("  本机：  http://127.0.0.1:%d" % port)
    print("  局域网：http://%s:%d" % (ip, port))
    print("=" * 56)
    print("  Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.shutdown()


if __name__ == "__main__":
    main()
