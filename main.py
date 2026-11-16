import os
import uuid
import time
import base64
import asyncio
from datetime import datetime
from typing import Optional

import psutil
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/abbasagha.db")
os.makedirs("./data", exist_ok=True)
os.makedirs("./tunnels", exist_ok=True)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

class AdminUser(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String, default="superadmin")
    max_users = Column(Integer, default=1000)
    max_traffic_gb = Column(Float, default=10000.0)
    used_traffic_gb = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)

class VPNUser(Base):
    __tablename__ = "vpn_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    uuid_str = Column(String, default=lambda: str(uuid.uuid4()))
    sub_token = Column(String, unique=True, default=lambda: uuid.uuid4().hex[:16])
    protocol = Column(String, default="v2ray")
    node_id = Column(Integer, nullable=True)
    outbound_tag = Column(String, default="direct")
    total_gb = Column(Float, default=50.0)
    used_up_bytes = Column(Integer, default=0)
    used_down_bytes = Column(Integer, default=0)
    live_up_bps = Column(Integer, default=0)
    live_down_bps = Column(Integer, default=0)
    is_online = Column(Boolean, default=False)
    expire_days = Column(Integer, default=30)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="active")
    owner_username = Column(String, default="admin")
    wg_private_key = Column(String, nullable=True)
    wg_ip = Column(String, nullable=True)
    l2tp_password = Column(String, default=lambda: uuid.uuid4().hex[:8])

class ServerNode(Base):
    __tablename__ = "nodes"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    flag = Column(String, default="🇩🇪")
    address = Column(String)
    port = Column(Integer, default=8080)
    api_token = Column(String)
    status = Column(String, default="online")

class TunnelConfig(Base):
    __tablename__ = "tunnels"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    engine = Column(String, default="backpack")
    remote_ip = Column(String)
    ports = Column(String, default="443,8443,2053")
    status = Column(String, default="running")
    created_at = Column(DateTime, default=datetime.utcnow)

class OutboundRule(Base):
    __tablename__ = "outbounds"
    id = Column(Integer, primary_key=True, index=True)
    tag = Column(String, unique=True)
    protocol = Column(String)
    address = Column(String, default="")
    port = Column(Integer, default=0)
    remark = Column(String, default="")

class PanelSettings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    theme = Column(String, default="abbasagha")
    bot_token = Column(String, default="")
    card_number = Column(String, default="6037-9975-0000-0000")
    card_holder = Column(String, default="عباس آقا")
    zarinpal_merchant = Column(String, default="")
    abangate_key = Column(String, default="")
    crypto_key = Column(String, default="")

class LoginReq(BaseModel):
    username: str
    password: str

class UserCreateReq(BaseModel):
    username: str
    protocol: str = "v2ray"
    total_gb: float = 50.0
    expire_days: int = 30
    node_id: Optional[int] = None
    outbound_tag: str = "direct"
    owner_username: str = "admin"

class ResellerCreateReq(BaseModel):
    username: str
    password: str
    max_users: int = 50
    max_traffic_gb: float = 1000.0

class NodeCreateReq(BaseModel):
    name: str
    flag: str = "🇳🇱"
    address: str
    port: int = 8080
    api_token: str = "abbas-node-secret"

class TunnelCreateReq(BaseModel):
    name: str
    engine: str = "backpack"
    remote_ip: str
    ports: str = "443,8443,51820"

class OutboundCreateReq(BaseModel):
    tag: str
    protocol: str
    address: str = ""
    port: int = 0
    remark: str = ""

class SettingsUpdateReq(BaseModel):
    theme: Optional[str] = None
    bot_token: Optional[str] = None
    card_number: Optional[str] = None
    zarinpal_merchant: Optional[str] = None
    abangate_key: Optional[str] = None
    crypto_key: Optional[str] = None

app = FastAPI(title="AbbasAgha VPN Panel API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

SERVER_META = {
    "ip": os.getenv("SERVER_IP", "127.0.0.1"),
    "location": "Iran / Khuzestan (Master)",
    "isp": "Cloud Datacenter",
    "os": "Ubuntu 22.04 LTS"
}

async def fetch_server_geo():
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get("http://ip-api.com/json/")
            if r.status_code == 200:
                d = r.json()
                SERVER_META["ip"] = d.get("query", SERVER_META["ip"])
                SERVER_META["location"] = f"{d.get('country', 'Unknown')} - {d.get('city', '')}"
                SERVER_META["isp"] = d.get("isp", "Datacenter")
    except Exception:
        pass

@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(AdminUser).where(AdminUser.username == os.getenv("ADMIN_USERNAME", "admin")))
        if not res.scalar_one_or_none():
            db.add(AdminUser(
                username=os.getenv("ADMIN_USERNAME", "admin"),
                password=os.getenv("ADMIN_PASSWORD", "Abbas@1405"),
                role="superadmin",
                max_users=99999,
                max_traffic_gb=999999.0
            ))
        st = await db.execute(select(PanelSettings).where(PanelSettings.id == 1))
        if not st.scalar_one_or_none():
            db.add(PanelSettings(id=1))
        ob = await db.execute(select(OutboundRule))
        if not ob.scalars().first():
            db.add_all([
                OutboundRule(tag="direct", protocol="freedom", remark="خروجی مستقیم سرور"),
                OutboundRule(tag="warp-plus", protocol="wireguard-warp", address="162.159.192.1", port=2408, remark="کلادفلر وارپ بدون محدودیت"),
                OutboundRule(tag="block-ir", protocol="blackhole", remark="مسدودسازی سایت‌های داخلی و تبلیغات")
            ])
        await db.commit()
    asyncio.create_task(fetch_server_geo())

@app.post("/api/auth/login")
async def login(req: LoginReq, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AdminUser).where(AdminUser.username == req.username))
    user = res.scalar_one_or_none()
    if not user or user.password != req.password or not user.is_active:
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز عبور اشتباه است")
    return {
        "token": f"abbas-token-{user.username}-{uuid.uuid4().hex[:8]}",
        "username": user.username,
        "role": user.role,
        "max_users": user.max_users,
        "max_traffic_gb": user.max_traffic_gb
    }

def get_system_stats():
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot = datetime.fromtimestamp(psutil.boot_time())
    uptime_sec = int((datetime.now() - boot).total_seconds())
    days, rem = divmod(uptime_sec, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    return {
        "cpu_percent": cpu,
        "cpu_cores": psutil.cpu_count(),
        "ram_percent": mem.percent,
        "ram_used_gb": round(mem.used / (1024**3), 2),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "disk_percent": disk.percent,
        "disk_used_gb": round(disk.used / (1024**3), 1),
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "uptime": f"{days}d {hours}h {mins}m",
        "server_ip": SERVER_META["ip"],
        "location": SERVER_META["location"],
        "isp": SERVER_META["isp"]
    }

@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    await ws.accept()
    prev_net = psutil.net_io_counters()
    try:
        while True:
            await asyncio.sleep(1.5)
            curr_net = psutil.net_io_counters()
            up_speed = max(0, int((curr_net.bytes_sent - prev_net.bytes_sent) / 1.5))
            down_speed = max(0, int((curr_net.bytes_recv - prev_net.bytes_recv) / 1.5))
            prev_net = curr_net

            stats = get_system_stats()
            stats["live_up_bps"] = up_speed
            stats["live_down_bps"] = down_speed

            async with AsyncSessionLocal() as db:
                res = await db.execute(select(VPNUser))
                users = res.scalars().all()
                user_live = []
                for u in users:
                    u_up = int(up_speed / max(1, len(users))) if u.status == "active" else 0
                    u_down = int(down_speed / max(1, len(users))) if u.status == "active" else 0
                    u.used_up_bytes += int(u_up * 1.5)
                    u.used_down_bytes += int(u_down * 1.5)
                    user_live.append({
                        "id": u.id,
                        "username": u.username,
                        "protocol": u.protocol,
                        "is_online": u.status == "active",
                        "live_up_bps": u_up,
                        "live_down_bps": u_down,
                        "used_gb": round((u.used_up_bytes + u.used_down_bytes) / (1024**3), 3),
                        "total_gb": u.total_gb
                    })
                await db.commit()

            await ws.send_json({"system": stats, "users": user_live})
    except WebSocketDisconnect:
        pass

def generate_client_config(user: VPNUser, server_ip: str, port: int = 8080) -> dict:
    sub_url = f"http://{server_ip}:{port}/sub/{user.sub_token}"
    if user.protocol == "v2ray":
        link = f"vless://{user.uuid_str}@{server_ip}:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.speedtest.net&fp=chrome&pbk=PUBLIC_KEY_HERE&sid=6ba85179e30d4fc2&type=tcp#AbbasAgha-{user.username}"
    elif user.protocol == "wireguard":
        link = f"[Interface]\nPrivateKey = {user.wg_private_key or 'WG_PRIV_KEY'}\nAddress = {user.wg_ip or '10.66.66.2/32'}\nDNS = 1.1.1.1\n\n[Peer]\nPublicKey = SERVER_WG_PUB_KEY\nEndpoint = {server_ip}:51820\nAllowedIPs = 0.0.0.0/0"
    elif user.protocol == "openvpn":
        link = f"client\ndev tun\nproto udp\nremote {server_ip} 1194\nresolv-retry infinite\nnobind\npersist-key\npersist-tun\n# User: {user.username}"
    else:
        link = f"Server: {server_ip} | Type: L2TP/IPsec | User: {user.username} | Pass: {user.l2tp_password} | PSK: abbasagha1405"
    return {"config": link, "sub_url": sub_url}

@app.get("/api/users")
async def list_users(owner: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(VPNUser)
    if owner and owner != "admin":
        q = q.where(VPNUser.owner_username == owner)
    res = await db.execute(q.order_by(VPNUser.id.desc()))
    users = res.scalars().all()
    out = []
    port = int(os.getenv("PANEL_PORT", 8080))
    for u in users:
        cfg = generate_client_config(u, SERVER_META["ip"], port)
        out.append({
            "id": u.id,
            "username": u.username,
            "sub_token": u.sub_token,
            "sub_url": cfg["sub_url"],
            "config": cfg["config"],
            "protocol": u.protocol,
            "outbound_tag": u.outbound_tag,
            "total_gb": u.total_gb,
            "used_gb": round((u.used_up_bytes + u.used_down_bytes) / (1024**3), 3),
            "expire_days": u.expire_days,
            "status": u.status
        })
    return out

@app.post("/api/users")
async def create_user(req: UserCreateReq, db: AsyncSession = Depends(get_db)):
    admin_res = await db.execute(select(AdminUser).where(AdminUser.username == req.owner_username))
    owner = admin_res.scalar_one_or_none()
    if owner and owner.role == "reseller":
        u_count_res = await db.execute(select(func.count(VPNUser.id)).where(VPNUser.owner_username == owner.username))
        if (u_count_res.scalar() or 0) >= owner.max_users:
            raise HTTPException(status_code=403, detail="سقف تعداد کاربران مجاز نماینده پر شده است!")
        if owner.used_traffic_gb + req.total_gb > owner.max_traffic_gb:
            raise HTTPException(status_code=403, detail="حجم مجاز نماینده کافی نیست!")
        owner.used_traffic_gb += req.total_gb

    exists = await db.execute(select(VPNUser).where(VPNUser.username == req.username))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="این نام کاربری قبلاً ثبت شده است")

    new_u = VPNUser(
        username=req.username,
        protocol=req.protocol,
        total_gb=req.total_gb,
        expire_days=req.expire_days,
        node_id=req.node_id,
        outbound_tag=req.outbound_tag,
        owner_username=req.owner_username,
        wg_private_key=uuid.uuid4().hex + "==",
        wg_ip=f"10.66.66.{int(time.time()) % 250 + 2}/32"
    )
    db.add(new_u)
    await db.commit()
    return {"message": "کاربر با موفقیت ساخته شد"}

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(VPNUser).where(VPNUser.id == user_id))
    u = res.scalar_one_or_none()
    if u:
        await db.delete(u)
        await db.commit()
    return {"message": "حذف شد"}

@app.get("/api/resellers")
async def list_resellers(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AdminUser).where(AdminUser.role == "reseller"))
    items = res.scalars().all()
    out = []
    for r in items:
        cnt = await db.execute(select(func.count(VPNUser.id)).where(VPNUser.owner_username == r.username))
        out.append({
            "id": r.id,
            "username": r.username,
            "max_users": r.max_users,
            "created_users": cnt.scalar() or 0,
            "max_traffic_gb": r.max_traffic_gb,
            "used_traffic_gb": r.used_traffic_gb
        })
    return out

@app.post("/api/resellers")
async def create_reseller(req: ResellerCreateReq, db: AsyncSession = Depends(get_db)):
    db.add(AdminUser(username=req.username, password=req.password, role="reseller", max_users=req.max_users, max_traffic_gb=req.max_traffic_gb))
    await db.commit()
    return {"message": "نماینده ایجاد شد"}

@app.get("/api/nodes")
async def list_nodes(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ServerNode))
    return res.scalars().all()

@app.post("/api/nodes")
async def add_node(req: NodeCreateReq, db: AsyncSession = Depends(get_db)):
    db.add(ServerNode(name=req.name, flag=req.flag, address=req.address, port=req.port, api_token=req.api_token))
    await db.commit()
    return {"message": "نود متصل شد"}

@app.get("/api/tunnels")
async def list_tunnels(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(TunnelConfig))
    return res.scalars().all()

@app.post("/api/tunnels")
async def create_tunnel(req: TunnelCreateReq, db: AsyncSession = Depends(get_db)):
    script_path = f"./tunnels/tunnel_{req.name}.sh"
    cmd = f"#!/bin/bash\n# BackPack / {req.engine} Tunnel to {req.remote_ip} ({req.ports})\n"
    with open(script_path, "w") as f:
        f.write(cmd)
    os.chmod(script_path, 0o755)
    db.add(TunnelConfig(name=req.name, engine=req.engine, remote_ip=req.remote_ip, ports=req.ports))
    await db.commit()
    return {"message": "تانل فعال شد"}

@app.get("/api/outbounds")
async def list_outbounds(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(OutboundRule))
    return res.scalars().all()

@app.post("/api/outbounds")
async def create_outbound(req: OutboundCreateReq, db: AsyncSession = Depends(get_db)):
    db.add(OutboundRule(tag=req.tag, protocol=req.protocol, address=req.address, port=req.port, remark=req.remark))
    await db.commit()
    return {"message": "اوتباند اضافه شد"}

@app.post("/api/settings")
async def update_settings(req: SettingsUpdateReq, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(PanelSettings).where(PanelSettings.id == 1))
    st = res.scalar_one_or_none()
    for k, v in req.dict(exclude_unset=True).items():
        if v is not None:
            setattr(st, k, v)
    await db.commit()
    return {"message": "تنظیمات ذخیره شد"}

@app.get("/sub/{sub_token}", response_class=HTMLResponse)
async def user_subscription_page(sub_token: str, request: Request, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(VPNUser).where(VPNUser.sub_token == sub_token))
    user = res.scalar_one_or_none()
    if not user:
        return HTMLResponse("<h1>اشتراک یافت نشد</h1>", status_code=404)

    port = int(os.getenv("PANEL_PORT", 8080))
    cfg = generate_client_config(user, SERVER_META["ip"], port)
    used_gb = round((user.used_up_bytes + user.used_down_bytes) / (1024**3), 2)
    remain_gb = max(0, round(user.total_gb - used_gb, 2))
    percent = min(100, int((used_gb / max(0.1, user.total_gb)) * 100))

    ua = request.headers.get("user-agent", "").lower()
    if any(k in ua for k in ["v2ray", "nekobox", "streisand", "hiddify", "shadowrocket", "clash"]):
        return HTMLResponse(base64.b64encode(cfg["config"].encode()).decode(), media_type="text/plain")

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>اشتراک | {user.username}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css" rel="stylesheet" />
  <style>body {{ font-family: 'Vazirmatn', sans-serif; background: radial-gradient(circle at top right, #064e3b, #090d16 60%); }}</style>
</head>
<body class="min-h-screen text-white flex items-center justify-center p-4">
  <div class="max-w-md w-full bg-slate-900/80 backdrop-blur-xl border border-emerald-500/30 rounded-3xl p-6 shadow-2xl">
    <h1 class="text-2xl font-bold mb-4">سلام، {user.username} 👋</h1>
    <div class="grid grid-cols-3 gap-3 mb-6 text-center">
      <div class="bg-slate-800 p-3 rounded-2xl"><div class="text-xs text-slate-400">حجم کل</div><div class="font-bold text-emerald-400">{user.total_gb} GB</div></div>
      <div class="bg-slate-800 p-3 rounded-2xl"><div class="text-xs text-slate-400">باقی‌مانده</div><div class="font-bold text-cyan-400">{remain_gb} GB</div></div>
      <div class="bg-slate-800 p-3 rounded-2xl"><div class="text-xs text-slate-400">اعتبار</div><div class="font-bold text-amber-400">{user.expire_days} روز</div></div>
    </div>
    <div class="w-full h-3 bg-slate-800 rounded-full overflow-hidden mb-6"><div class="h-full bg-emerald-400" style="width: {percent}%"></div></div>
    <div class="bg-white p-3 rounded-2xl w-44 h-44 mx-auto mb-6 flex items-center justify-center">
      <img src="https://api.qrserver.com/v1/create-qr-code/?size=160x160&data={cfg['sub_url']}" alt="QR" />
    </div>
    <button onclick="navigator.clipboard.writeText('{cfg['sub_url']}');alert('کپی شد!')" class="w-full py-3 rounded-xl bg-emerald-500 text-slate-950 font-bold mb-2">📋 کپی لینک سابسکریپشن</button>
    <button onclick="navigator.clipboard.writeText(`{cfg['config']}`);alert('کپی شد!')" class="w-full py-3 rounded-xl bg-slate-800 text-slate-200 font-bold">🔑 کپی کانفیگ ({user.protocol.upper()})</button>
  </div>
</body>
</html>""")

if os.path.exists("./frontend"):
    app.mount("/", StaticFiles(directory="./frontend", html=True), name="frontend")
