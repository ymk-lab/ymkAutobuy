# Cloudflare tunnel（前端永久網址）

## Named tunnel（建議）

1. Cloudflare Zero Trust → Networks → Tunnels → Create  
2. Public hostname → 指向 `http://127.0.0.1:8787`  
3. 複製 tunnel token → `.env`：

```bash
CLOUDFLARE_TUNNEL_TOKEN=eyJ...
```

4. UI 先起來，再跑永久隧道：

```bash
PYTHONPATH=src python3 -m uvicorn qresearch.web.paper_app:app --host 0.0.0.0 --port 8787
bash deploy/cloudflare/run-named-tunnel.sh
```

## Quick tunnel（臨時）

```bash
bash deploy/cloudflare/run-quick-tunnel.sh
```

每次重啟 URL 會變，只適合測試。
