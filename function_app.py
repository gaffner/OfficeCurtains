import azure.functions as func

from server import app as fastapi_app

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
asgi_middleware = func.AsgiMiddleware(fastapi_app)


@app.route(route="{*route}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def office_curtains(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    return await asgi_middleware.handle_async(req, context)
