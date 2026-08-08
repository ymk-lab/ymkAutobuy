# Cloud Run API + Firebase Hosting

Firebase **不能**跑富途 OpenD。可行架構：

```
Browser → https://ymk-autobuy.web.app          (Firebase Hosting UI)
       → https://ymk-autobuy.web.app/api/**   (rewrite → Cloud Run FastAPI)
Cloud Run → OpenD :11111                      (必須在可連線的 VPS / GCE)
```

本機 OpenD（127.0.0.1）**無法**被 Cloud Run 直接連到；交易／同步帳戶要把 OpenD 放到 VPS，或暫時繼續用本機隧道當 API。

## 一鍵（Windows，需 gcloud）

1. 安裝 [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)，登入：

```powershell
gcloud auth login
gcloud config set project ymk-autobuy
```

2. 部署 API + 更新 Firebase rewrite：

```powershell
cd C:\Users\STANYIU\ymkAutobuy
git pull origin main
cd deploy\cloudrun
.\deploy.ps1 -ProjectId ymk-autobuy -Region asia-east1
```

3. 開 https://ymk-autobuy.web.app （同源 `/api`，頁腳 API 可留空／清掉舊隧道）

## OpenD（若要同步／下單）

在 **VPS / GCE** 安裝並登入 OpenD，對 Cloud Run 開放 `11111`（建議僅內網／防火牆白名單）。

Cloud Run 環境變數（deploy.ps1 可改）：

| 變數 | 說明 |
|------|------|
| `FUTU_OPEND_HOST` | OpenD 主機 IP／hostname |
| `FUTU_OPEND_PORT` | 預設 `11111` |
| `FUTU_TRD_ENV` | `SIMULATE` |
| `QRESEARCH_FUTU_ALLOW_LIVE` | 保持 `0` |
| `QRESEARCH_SG_PAPER_SUBMIT` | `0` 只計畫；`1` 才送單 |

沒有可連的 OpenD 時：UI 仍可開，但「同步帳戶／送單」會失敗；回測／讀本地產物視磁碟而定（Cloud Run 檔案不持久）。

## 暫時方案（OpenD 仍在筆電）

繼續：

```powershell
.\deploy\local\start-backend.bat
```

Firebase 頁腳貼 `trycloudflare` 網址。這不是「API 上雲」，但可交易。
