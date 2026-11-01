"""The MCP service: its HTTP app and its start command (FDS section 15.3, R20.8).

A Cloud Run service of its own serves the MCP server next to the application, from the same
image with another start command, `python -m dimonapp.mcp_service`. It never applies
migrations. Streamable HTTP runs stateless: every request stands alone, so nothing depends on
a session that a restart or a scale to zero of Cloud Run would lose.
"""

import logging
from typing import Optional

import sqlalchemy as sa
import uvicorn
from fastmcp.utilities.lifespan import combine_lifespans
from starlette.applications import Starlette
from starlette.routing import Mount

from dimonapp.mcp_auth import AdminGoogleProvider, build_google_provider
from dimonapp.mcp_database import create_mcp_engine
from dimonapp.mcp_public import build_public_server
from dimonapp.mcp_server import build_mcp_server
from dimonapp.mcp_settings import McpSettings, has_sign_in, load_mcp_settings

logger = logging.getLogger(__name__)

# The public server answers at /public/mcp (R20.5), the server with the data tools at /mcp.
PUBLIC_PREFIX = '/public'
MCP_PATH = '/mcp'


def build_sign_in(settings: McpSettings, engine: sa.Engine) -> Optional[AdminGoogleProvider]:
    """Give the Google sign-in of /mcp, or None where the settings allow it.

    The settings allow it only in TEST on the developer's machine; in ACC and PROD they
    refuse to load without sign-in (R20.7).
    """
    if has_sign_in(settings=settings):
        logger.info('/mcp is served with Google sign-in, for active admins only.')
        return build_google_provider(settings=settings, engine=engine)
    app_env = settings.app_env
    logger.warning(f'/mcp is served without sign-in, as {app_env} allows on the local database.')
    return None


def build_mcp_app(settings: McpSettings) -> Starlette:
    """Build the HTTP app of the service: the public endpoint, and /mcp with a database user.

    The OAuth routes of the sign-in (discovery, registration, /auth/callback) come with the
    app of /mcp, at the root of the service. Without sign-in, /mcp only answers requests
    addressed to the developer's machine, so a web page cannot reach it through DNS
    rebinding; with sign-in, a web page cannot add an admin's token anyway (R20.7).
    """
    public_server = build_public_server()
    public_app = public_server.http_app(path=MCP_PATH, stateless_http=True)
    routes = [Mount(PUBLIC_PREFIX, app=public_app)]
    lifespans = [public_app.lifespan]
    if not settings.mcp_database_url:
        logger.info('No MCP_DATABASE_URL: /mcp is not served.')
    else:
        engine = create_mcp_engine(settings=settings)
        auth = build_sign_in(settings=settings, engine=engine)
        mcp_server = build_mcp_server(engine=engine, auth=auth)
        mcp_app = mcp_server.http_app(
            path=MCP_PATH,
            stateless_http=True,
            host_origin_protection=auth is None,
        )
        routes.append(Mount('', app=mcp_app))
        lifespans.append(mcp_app.lifespan)
    # Starlette does not run the lifespan of a mounted app, so the service runs them.
    return Starlette(routes=routes, lifespan=combine_lifespans(*lifespans))


def main() -> None:
    """Serve the MCP server over HTTP on the configured port."""
    logging.basicConfig(level=logging.INFO)
    settings = load_mcp_settings()
    app = build_mcp_app(settings=settings)
    app_env = settings.app_env
    port = settings.port
    logger.info(f'Starting the MCP service of {app_env} on port {port}.')
    uvicorn.run(app=app, host=settings.mcp_host, port=port)


if __name__ == '__main__':
    main()
