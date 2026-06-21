from aiohttp import web
from web.server import routes

web_app = web.Application()
web_app.add_routes(routes)
