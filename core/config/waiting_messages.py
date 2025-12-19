# Configuration for Smart Search Waiting Messages
# Each item represents a notification step.
# 'delay': Seconds to wait *after the previous step* (or start) before sending this message.
# 'message': The text to send to the user. Markdown is supported.

SMART_SEARCH_WAITING_MESSAGES = [
    {
        "delay": 0,
        "message": "\n\n> ⏳ Поиск может занять длительное время, пожалуйста подождите..."
    },
    {
        "delay": 10,
        "message": "\n\n> 🔄 Я не завис, поиск продолжается, не беспокойтесь"
    },
    {
        "delay": 10,
        "message": "\n\n> 🧐 Поиск занимает дольше времени чем обычно, я всё еще работаю над вашим запросом..."
    }
]
