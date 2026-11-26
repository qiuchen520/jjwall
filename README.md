# 掘金壁纸 · 独立版

小红书小程序「掘金壁纸」的接口逆向 + 独立运行版。不依赖小红书，不需要 App。

## 怎么来的

反编译小红书缓存目录里的小程序包：
`/data/data/com.xingin.xhs/files/redmpV2/release/67905222993c2f0001ad0fd6/`

在 `service.js` 里找到：

- API 主机 `https://min-api.xliii.cn/`
- AES 密钥 `WAG0JIUGYALACVJF`（就是代码里的 `vote_key`）
- 加密方式 `AES-128-CBC` + PKCS7，业务参数整体加密后放进 `requestData`
- 响应 `data.data` 用 `data.iv` 解密

## 两个版本

### A. Cloudflare Worker（公网，手机就能部署）

用 `jjwall_worker.js`：

1. https://dash.cloudflare.com/ 注册
2. Workers & Pages -> Create -> Workers -> Create Worker
3. 名字 `jjwall` -> Deploy
4. Edit code，把 `jjwall_worker.js` 全部粘进去
5. Deploy
6. 得到 `https://jjwall.xxx.workers.dev`

### B. Termux 本地版

```bash
pkg update -y
pkg install python -y
curl -L -o jjwall.py https://raw.githubusercontent.com/qiuchen520/jjwall/main/jjwall.py
python jjwall.py
```

手机浏览器打开 `http://127.0.0.1:8700`

零依赖：只需要 python3 本身，AES 是纯 Python 实现的。

## 接口

| 名字 | 路径 |
|---|---|
| home | miniapi/Product/home |
| pageIndex | miniapi/Product/pageIndex |
| albumList | miniapi/Product/albumList |
| albumDataPage | miniapi/Product/albumDataPage |
| singleData | miniapi/Product/singleData |

图片：`https://min-cdn.xliii.cn/` + img / thumb / preview，CDN 公开无防盗链。
