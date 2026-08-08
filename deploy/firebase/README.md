# Firebase Hosting — Structure Gate UI

## 架構（推薦：UI + API 上雲）

```
瀏覽器 → https://ymk-autobuy.web.app           (Firebase Hosting UI)
       → https://ymk-autobuy.web.app/api/**    (rewrite → Cloud Run)
Cloud Run → OpenD                                (需 VPS；見 deploy/cloudrun/)
```

一鍵部署 API + Hosting：`deploy/cloudrun/deploy-all.bat`（需 gcloud）。

## 暫時：UI 上雲 + API 仍在本機

Firebase 只託管**前端**。本機 uvicorn + OpenD，用隧道給前端呼叫：

```
瀏覽器 → https://YOUR_PROJECT.web.app  (Firebase Hosting)
       → https://your-tunnel…/api/sg/* (本機 uvicorn :8787 + OpenD)
```

## 前置

1. [Firebase Console](https://console.firebase.google.com/) 建立專案，開啟 **Hosting**
2. 本機已能跑 UI：`uvicorn qresearch.web.paper_app:app --host 127.0.0.1 --port 8787`
3. 有公開 API 網址（建議 Cloudflare named tunnel，見 `deploy/cloudflare/`）

## 一次部署（Windows PowerShell）

```powershell
Set-Location C:\Users\STANYIU\ymkAutobuy
git pull origin main

# 1) 後端 + 隧道先起來（範例）
$env:PYTHONPATH = "$PWD\src"
$env:PYTHONIOENCODING = "utf-8"
$env:QRESEARCH_CORS_ORIGINS = "https://YOUR_PROJECT.web.app,https://YOUR_PROJECT.firebaseapp.com"
# 另開視窗跑 uvicorn 與 cloudflared…

# 2) 部署 Firebase（把 API_BASE 設成隧道網址）
Set-Location deploy\firebase
npm install
copy .firebaserc.example .firebaserc
# 編輯 .firebaserc → 填入 Firebase project id
firebase login
$env:QRESEARCH_API_BASE = "https://YOUR_TUNNEL_HOSTNAME"
npm run deploy
```

成功後網址：

- `https://YOUR_PROJECT.web.app`
- `https://YOUR_PROJECT.firebaseapp.com`

頁腳會顯示 `API: https://…`；按「同步帳戶」應打到隧道後端。

## 環境變數

| 變數 | 用在 | 說明 |
|------|------|------|
| `QRESEARCH_API_BASE` | `npm run build/deploy` | 寫入 `public/config.js`，前端打 API 的 origin |
| `QRESEARCH_CORS_ORIGINS` | 本機 uvicorn | 允許的 Firebase 來源；可用 `*` 測試 |
| `QRESEARCH_PUBLIC_API_BASE` | 本機 `/config.js` | 本機同源時通常留空 |

## 指令

```bash
cd deploy/firebase
npm install
npm run build          # 只建置 public/
npm run serve          # 本機預覽 Hosting
npm run deploy         # build + firebase deploy --only hosting
```

## 注意

- **不能**把 OpenD／送單邏輯放到 Firebase Functions：必須連本機／VPS 上的 OpenD。
- 換隧道網址後要重跑 `npm run deploy`（或至少 rebuild + deploy），否則 `config.js` 仍是舊 API。
- 送單仍受 `.env` 的 `QRESEARCH_SG_PAPER_SUBMIT` / `QRESEARCH_FUTU_ALLOW_LIVE` 約束。
