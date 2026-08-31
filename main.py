import os
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import requests

from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# ------------------------------------------------------------------
# 1. НАСТРОЙКИ И БАЗА ДАННЫХ
# ------------------------------------------------------------------

BOT_TOKEN = "ТВОЙ_ТОКЕН_БОТА"
CHAT_ID = "ТВОЙ_CHAT_ID"
ADMIN_KEY = "admin123"  # Секретный ключ для доступа к админке

DATABASE_URL = "sqlite:///./orders.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Модель таблицы Заказов в БД
class OrderModel(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(String, nullable=False)
    item_name = Column(String, nullable=False)
    price = Column(Integer, nullable=False)
    category = Column(String, nullable=False)  # 'uc' или 'car'
    status = Column(String, default="NEW")     # NEW, PAID, COMPLETED, CANCELLED
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# Зависимость для получения сессии БД
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ------------------------------------------------------------------
# 2. FASTAPI ПРИЛОЖЕНИЕ И СХЕМЫ
# ------------------------------------------------------------------

app = FastAPI(title="CODEX UC SHOP API & ADMIN")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class OrderCreate(BaseModel):
    player_id: str = Field(..., min_length=7, max_length=12, regex="^[0-9]+$")
    item_name: str
    price: int
    category: str

class OrderStatusUpdate(BaseModel):
    status: str

# ------------------------------------------------------------------
# 3. ВПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ------------------------------------------------------------------

def send_telegram_notification(order_id: int, player_id: str, item_name: str, price: int, category: str):
    icon = "💎" if category == "uc" else "🏎️"
    message = (
        f"{icon} *НОВЫЙ ЗАКАЗ №{order_id} — CODEX UC SHOP*\n\n"
        f"👤 *Player ID:* `{player_id}`\n"
        f"📦 *Товар:* {item_name}\n"
        f"💰 *Сумма:* {price} ₽\n"
        f"📊 *Статус:* Создан (NEW)"
    )
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")

# Проверка авторизации админа
def verify_admin(x_admin_key: Optional[str] = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Доступ запрещен: неверный X-Admin-Key")

# ------------------------------------------------------------------
# 4. API ЭНДПОИНТЫ ДЛЯ КЛИЕНТОВ
# ------------------------------------------------------------------

@app.post("/api/orders")
async def create_order(order_data: OrderCreate, db: Session = Depends(get_db)):
    # Сохраняем заказ в локальную базу SQLite
    db_order = OrderModel(
        player_id=order_data.player_id,
        item_name=order_data.item_name,
        price=order_data.price,
        category=order_data.category
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)

    # Отправляем уведомление
    send_telegram_notification(
        order_id=db_order.id,
        player_id=db_order.player_id,
        item_name=db_order.item_name,
        price=db_order.price,
        category=db_order.category
    )

    return {
        "status": "success",
        "order_id": db_order.id,
        "message": "Заказ успешно зарегистрирован"
    }

# ------------------------------------------------------------------
# 5. API ЭНДПОИНТЫ ДЛЯ АДМИНКИ
# ------------------------------------------------------------------

@app.get("/api/admin/orders", dependencies=[Depends(verify_admin)])
async def get_all_orders(db: Session = Depends(get_db)):
    orders = db.query(OrderModel).order_by(OrderModel.id.desc()).all()
    return orders

@app.patch("/api/admin/orders/{order_id}/status", dependencies=[Depends(verify_admin)])
async def update_order_status(order_id: int, payload: OrderStatusUpdate, db: Session = Depends(get_db)):
    order = db.query(OrderModel).filter(OrderModel.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    
    order.status = payload.status
    db.commit()
    return {"status": "success", "new_status": order.status}

# ------------------------------------------------------------------
# 6. АДМИН-ПАНЕЛЬ (Встроенный HTML)
# ------------------------------------------------------------------

@app.get("/admin")
async def admin_page():
    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Панель управления — CODEX UC SHOP</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    </head>
    <body class="bg-[#0B0C10] text-gray-100 font-sans p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            <div class="flex justify-between items-center border-b border-[#262933] pb-4">
                <h1 class="text-2xl font-bold text-[#ff1a1a]">Управление заказами CODEX SHOP</h1>
                <input type="password" id="adminKey" placeholder="Введите Admin Key" class="bg-[#14161D] border border-[#262933] px-3 py-2 rounded text-sm text-white focus:outline-none focus:border-[#ff1a1a]" oninput="loadOrders()">
            </div>

            <div class="bg-[#14161D] border border-[#262933] rounded-xl p-4 overflow-x-auto shadow-2xl">
                <table class="w-full text-left text-sm">
                    <thead>
                        <tr class="border-b border-[#262933] text-gray-400">
                            <th class="p-3">ID</th>
                            <th class="p-3">Player ID</th>
                            <th class="p-3">Товар</th>
                            <th class="p-3">Цена</th>
                            <th class="p-3">Категория</th>
                            <th class="p-3">Дата</th>
                            <th class="p-3">Статус</th>
                        </tr>
                    </thead>
                    <tbody id="ordersTable">
                        <tr><td colspan="7" class="p-4 text-center text-gray-500">Введите правильный Admin Key для загрузки данных</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <script>
            async function loadOrders() {
                const key = document.getElementById('adminKey').value;
                try {
                    const res = await fetch('/api/admin/orders', {
                        headers: { 'X-Admin-Key': key }
                    });
                    if (!res.ok) return;

                    const orders = await res.json();
                    const tbody = document.getElementById('ordersTable');
                    tbody.innerHTML = orders.map(o => `
                        <tr class="border-b border-[#262933]/50 hover:bg-[#1f222d]">
                            <td class="p-3 font-mono font-bold text-gray-400">#${o.id}</td>
                            <td class="p-3 font-mono text-white">${o.player_id}</td>
                            <td class="p-3 font-semibold text-white">${o.item_name}</td>
                            <td class="p-3 text-[#ff1a1a] font-bold">${o.price} ₽</td>
                            <td class="p-3 uppercase text-xs font-bold text-gray-400">${o.category}</td>
                            <td class="p-3 text-xs text-gray-500">${new Date(o.created_at).toLocaleString('ru-RU')}</td>
                            <td class="p-3">
                                <select onchange="updateStatus(${o.id}, this.value)" class="bg-[#0B0C10] border border-[#262933] text-xs font-bold rounded px-2 py-1 text-white focus:outline-none">
                                    <option value="NEW" ${o.status === 'NEW' ? 'selected' : ''}>NEW (Новый)</option>
                                    <option value="PAID" ${o.status === 'PAID' ? 'selected' : ''}>PAID (Оплачен)</option>
                                    <option value="COMPLETED" ${o.status === 'COMPLETED' ? 'selected' : ''}>COMPLETED (Выполнен)</option>
                                    <option value="CANCELLED" ${o.status === 'CANCELLED' ? 'selected' : ''}>CANCELLED (Отменен)</option>
                                </select>
                            </td>
                        </tr>
                    `).join('');
                } catch(e) {}
            }

            async function updateStatus(id, newStatus) {
                const key = document.getElementById('adminKey').value;
                await fetch(`/api/admin/orders/${id}/status`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Admin-Key': key
                    },
                    body: JSON.stringify({ status: newStatus })
                });
            }
        </script>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)

# ------------------------------------------------------------------
# 7. РАЗДАЧА СТАТИКИ И ЗАПУСК СЕРВЕРА
# ------------------------------------------------------------------

app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)