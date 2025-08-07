# backend/app/bot/states.py
from aiogram.fsm.state import State, StatesGroup

class ManagerStates(StatesGroup):
    # Состояние для ожидания сообщения для рассылки
    mailing_confirm = State() 
    # Состояние для ожидания поискового запроса по клиентам
    customer_search_query = State() 
    # Состояние для ожидания сообщения для отправки конкретному клиенту
    message_to_customer = State()



class UserStates(StatesGroup):
    awaiting_contact = State() # Ожидание контакта по заказу
